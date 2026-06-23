"""构造微信回复 XML"""
import time

def _cdata(s: str) -> str:
    return f"<![CDATA[{s}]]>"

def text_reply(from_user: str, to_user: str, content: str) -> str:
    return f"""<xml>
<ToUserName>{_cdata(from_user)}</ToUserName>
<FromUserName>{_cdata(to_user)}</FromUserName>
<CreateTime>{int(time.time())}</CreateTime>
<MsgType>{_cdata('text')}</MsgType>
<Content>{_cdata(content)}</Content>
</xml>"""

def news_reply(from_user: str, to_user: str, articles: list[dict]) -> str:
    """图文消息回复，articles: [{title, description, picurl, url}]"""
    items = "".join(
        f"<item><Title>{_cdata(a['title'])}</Title><Description>{_cdata(a.get('description',''))}</Description>"
        f"<PicUrl>{_cdata(a.get('picurl',''))}</PicUrl><Url>{_cdata(a.get('url',''))}</Url></item>"
        for a in articles
    )
    return f"""<xml>
<ToUserName>{_cdata(from_user)}</ToUserName>
<FromUserName>{_cdata(to_user)}</FromUserName>
<CreateTime>{int(time.time())}</CreateTime>
<MsgType>{_cdata('news')}</MsgType>
<ArticleCount>{len(articles)}</ArticleCount>
<Articles>{items}</Articles>
</xml>"""
