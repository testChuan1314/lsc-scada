/**
 * LSC SCADA - ESP32 RS485/MQTT Bridge
 * =============================================
 *  1. MQTT receive config -> update poll table
 *  2. RS485 Modbus read -> forward raw hex to MQTT
 *  3. MQTT receive relay command -> GPIO write
 *  4. Periodic status report
 */
#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ============================================================
// 1. Pin Definitions (ESP32 4CH Modbus Relay Module)
// ============================================================
#define RS485_DE_RE  32
#define RS485_RX     18
#define RS485_TX     19

#define RELAY_1  23
#define RELAY_2  5
#define RELAY_3  4
#define RELAY_4  13

#define INPUT_1  25
#define INPUT_2  26
#define INPUT_3  27
#define INPUT_4  33

#define RELAY_COUNT 4

// ============================================================
// 2. Config Constants
// ============================================================
#ifndef WIFI_SSID
#define WIFI_SSID     "test"
#endif
#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD "13648080122"
#endif
#ifndef MQTT_SERVER
#define MQTT_SERVER   "192.168.1.14"
#endif
#ifndef DEVICE_ID
#define DEVICE_ID     "rtu-001"
#endif

#define MQTT_PORT         1883
#define MQTT_TOPIC_CONFIG "lsc/devices/" DEVICE_ID "/config"
#define MQTT_TOPIC_DATA   "lsc/devices/" DEVICE_ID "/data"
#define MQTT_TOPIC_STATUS "lsc/devices/" DEVICE_ID "/status"
#define MQTT_TOPIC_INPUT  "lsc/devices/" DEVICE_ID "/input"

// ============================================================
// 3. Global Objects
// ============================================================
WiFiClient    wifiClient;
PubSubClient  mqtt(wifiClient);

const int relayPins[RELAY_COUNT] = {RELAY_1, RELAY_2, RELAY_3, RELAY_4};
const int inputPins[RELAY_COUNT] = {INPUT_1, INPUT_2, INPUT_3, INPUT_4};
bool     inputState[RELAY_COUNT] = {false, false, false, false};
uint32_t lastInputCheck = 0;
uint32_t lastModbusTx   = 0;

// ============================================================
// 4. Poll Task Structure (fixed array)
// ============================================================
#define MAX_POLL_TASKS 16

struct PollTask {
  uint8_t  slave;
  uint16_t startReg;
  uint16_t count;
  uint32_t interval;
  uint32_t lastPoll;
  bool     active;
};

PollTask pollTable[MAX_POLL_TASKS];

// ============================================================
// 5. Modbus CRC16
// ============================================================
static uint16_t crc16(const uint8_t* data, size_t len) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < len; i++) {
    crc ^= data[i];
    for (int b = 0; b < 8; b++) {
      if (crc & 0x0001) crc = (crc >> 1) ^ 0xA001;
      else              crc >>= 1;
    }
  }
  return crc;
}

// ============================================================
// 6. Relay Control
// ============================================================
void relayWrite(int channel, bool on) {
  if (channel < 0 || channel >= RELAY_COUNT) return;
  digitalWrite(relayPins[channel], on ? LOW : HIGH);  // 低电平触发
  Serial.printf("[RELAY] ch=%d -> %s (pin=%s)\n", channel, on ? "ON" : "OFF", on ? "LOW" : "HIGH");
}

void relayInit() {
  for (int i = 0; i < RELAY_COUNT; i++) {
    pinMode(relayPins[i], OUTPUT);
    digitalWrite(relayPins[i], HIGH);  // 初始全关（高电平断开）
  }
  pinMode(INPUT_1, INPUT_PULLUP);
  pinMode(INPUT_2, INPUT_PULLUP);
  pinMode(INPUT_3, INPUT_PULLUP);
  pinMode(INPUT_4, INPUT_PULLUP);
}

// ============================================================
// 6b. Optocoupler Input Check
// ============================================================
void checkInputs() {
  bool changed = false;
  StaticJsonDocument<256> doc;
  JsonArray arr = doc.createNestedArray("inputs");

  for (int i = 0; i < RELAY_COUNT; i++) {
    bool now = digitalRead(inputPins[i]) == LOW;
    arr.add(now ? 1 : 0);
    if (now != inputState[i]) {
      changed = true;
      inputState[i] = now;
      Serial.printf("[INPUT] ch=%d -> %s\n", i, now ? "CLOSED" : "OPEN");
    }
  }

  if (changed) {
    doc["esp_id"] = DEVICE_ID;
    String out;
    serializeJson(doc, out);
    mqtt.publish(MQTT_TOPIC_INPUT, out.c_str());
  }
}

// ============================================================
// 7. Modbus Read (raw RS485, no library needed)
// ============================================================
String modbusReadHex(uint8_t slave, uint16_t startReg, uint16_t count) {
  uint8_t req[8];
  req[0] = slave;
  req[1] = 0x03;
  req[2] = (startReg >> 8) & 0xFF;
  req[3] = startReg & 0xFF;
  req[4] = (count >> 8) & 0xFF;
  req[5] = count & 0xFF;
  uint16_t crc = crc16(req, 6);
  req[6] = crc & 0xFF;
  req[7] = (crc >> 8) & 0xFF;

  digitalWrite(RS485_DE_RE, HIGH);
  Serial2.write(req, 8);
  Serial2.flush();
  digitalWrite(RS485_DE_RE, LOW);

  delay(50);

  String hex = "";
  hex.reserve(128);
  uint32_t start = millis();
  while (millis() - start < 200) {
    while (Serial2.available()) {
      uint8_t b = Serial2.read();
      char buf[3];
      snprintf(buf, 3, "%02X", b);
      hex += buf;
    }
  }
  return hex.length() >= 4 ? hex : "";
}

// ============================================================
// 8. Modbus Write Single Coil
// ============================================================
void modbusWriteCoil(uint8_t slave, uint16_t coilAddr, bool on) {
  uint8_t req[8];
  req[0] = slave;
  req[1] = 0x05;
  req[2] = (coilAddr >> 8) & 0xFF;
  req[3] = coilAddr & 0xFF;
  req[4] = on ? 0xFF : 0x00;
  req[5] = on ? 0x00 : 0x00;
  uint16_t crc = crc16(req, 6);
  req[6] = crc & 0xFF;
  req[7] = (crc >> 8) & 0xFF;

  digitalWrite(RS485_DE_RE, HIGH);
  Serial2.write(req, 8);
  Serial2.flush();
  digitalWrite(RS485_DE_RE, LOW);

  Serial.printf("[MODBUS] slave=0x%02X coil=0x%04X %s\n", slave, coilAddr, on ? "ON" : "OFF");
}

// ============================================================
// 9. MQTT Callback
// ============================================================
void mqttCallback(char* topic, byte* payload, unsigned int length) {
  char buf[1024] = {0};
  unsigned int len = length < 1023 ? length : 1023;
  memcpy(buf, payload, len);

  String topicStr(topic);
  String msg(buf);

  Serial.printf("[MQTT] << %s : %s\n", topic, buf);

  if (topicStr == MQTT_TOPIC_CONFIG) {
    StaticJsonDocument<2048> doc;
    DeserializationError err = deserializeJson(doc, msg);
    if (err) {
      Serial.printf("[CONFIG] JSON parse error: %s\n", err.c_str());
      return;
    }

    // 只有 polls 存在时才更新轮询（继电器指令不影响轮询）
    if (doc.containsKey("polls")) {
      for (int i = 0; i < MAX_POLL_TASKS; i++) pollTable[i].active = false;

      JsonArray polls = doc["polls"].as<JsonArray>();
      int idx = 0;
      for (JsonObject p : polls) {
        if (idx >= MAX_POLL_TASKS) break;
        pollTable[idx].slave    = p["slave"]    | 1;
        pollTable[idx].startReg = p["start"]    | 0;
        pollTable[idx].count    = p["count"]    | 1;
        pollTable[idx].interval = p["interval"] | 5000;
        pollTable[idx].lastPoll = 0;
        pollTable[idx].active   = true;
        idx++;
      }
      Serial.printf("[CONFIG] poll table updated, %d active\n", idx);
    }

    if (doc.containsKey("relay")) {
      JsonObject rel = doc["relay"];
      int  ch = rel["channel"] | -1;
      bool on = rel["on"]       | false;
      if (ch >= 0 && ch < RELAY_COUNT) {
        relayWrite(ch, on);
      }
    }
  }
}

// ============================================================
// 10. MQTT Reconnect
// ============================================================
void mqttReconnect() {
  while (!mqtt.connected()) {
    Serial.print("[MQTT] connecting...");
    String clientId = String(DEVICE_ID) + "-" + String(WiFi.macAddress());
    if (mqtt.connect(clientId.c_str())) {
      Serial.println(" connected");
      mqtt.subscribe(MQTT_TOPIC_CONFIG);

      // 等待 retain 消息到达（解决服务端先发、ESP 后连的时序问题）
      uint32_t waitStart = millis();
      while (millis() - waitStart < 1000) {
        mqtt.loop();
        delay(10);
      }

      StaticJsonDocument<128> doc;
      doc["status"] = "online";
      doc["ip"] = WiFi.localIP().toString();
      String out;
      serializeJson(doc, out);
      mqtt.publish(MQTT_TOPIC_STATUS, out.c_str());
    } else {
      Serial.printf(" failed rc=%d\n", mqtt.state());
      delay(3000);
    }
  }
}

// ============================================================
// 11. WiFi Connect
// ============================================================
void wifiConnect() {
  Serial.printf("[WIFI] connecting %s ...\n", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 20000) {
    delay(500);
    Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\n[WIFI] connected IP=%s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("\n[WIFI] timeout, restart...");
    ESP.restart();
  }
}

// ============================================================
// 12. Setup
// ============================================================
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n=== LSC SCADA ESP32 Bridge ===");
  Serial.printf("Device ID: %s\n", DEVICE_ID);

  relayInit();

  pinMode(RS485_DE_RE, OUTPUT);
  digitalWrite(RS485_DE_RE, LOW);
  Serial2.begin(4800, SERIAL_8N1, RS485_RX, RS485_TX);

  wifiConnect();
  mqtt.setServer(MQTT_SERVER, MQTT_PORT);
  mqtt.setBufferSize(2048);   // 默认 256，配置 JSON 600+ 字节会丢！
  mqtt.setCallback(mqttCallback);
  mqttReconnect();
}

// ============================================================
// 13. Main Loop
// ============================================================
void loop() {
  mqtt.loop();

  uint32_t now = millis();
  for (int i = 0; i < MAX_POLL_TASKS; i++) {
    if (!pollTable[i].active) continue;
    if (now - pollTable[i].lastPoll >= pollTable[i].interval) {
      // 总线碰撞保护：距上次发送不足 80ms 则跳过本轮
      if (now - lastModbusTx < 80) continue;
      pollTable[i].lastPoll = now;
      lastModbusTx = now;

      String hex = modbusReadHex(pollTable[i].slave, pollTable[i].startReg, pollTable[i].count);
      if (hex.length() > 0) {
        Serial.printf("[POLL] slave=0x%02X reg=0x%04X count=%d -> %s\n",
                      pollTable[i].slave, pollTable[i].startReg, pollTable[i].count, hex.c_str());
        mqtt.publish(MQTT_TOPIC_DATA, hex.c_str());
      } else {
        Serial.printf("[POLL] slave=0x%02X timeout\n", pollTable[i].slave);
      }
    }
  }

  // 光耦输入检测（每 500ms）
  if (now - lastInputCheck >= 500) {
    lastInputCheck = now;
    checkInputs();
  }

  if (!mqtt.connected()) {
    mqttReconnect();
  }

  delay(10);
}
