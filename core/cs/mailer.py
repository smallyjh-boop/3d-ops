"""发邮件（v2.22）：客服紧急事件、超时、跟进提醒、周报发到老板邮箱和客服邮箱。

设置（客服 → 知识库与话术 → 邮件通知）：
  smtp_host / smtp_port / smtp_tls（ssl = 465 端口，starttls = 587 端口）/ smtp_user / smtp_pass / smtp_from
  owner_email 老板邮箱，cs_email 客服邮箱（可以填几个，逗号分隔）
Gmail：smtp.gmail.com，465，ssl，用户名是邮箱，密码要用「应用专用密码」（Google 账号 → 安全性 → 两步验证 → 应用专用密码），不是登录密码。
"""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from . import data


KNOWN = {"gmail.com": "smtp.gmail.com", "googlemail.com": "smtp.gmail.com", "outlook.com": "smtp.office365.com",
         "hotmail.com": "smtp.office365.com", "live.com": "smtp.office365.com", "yahoo.com": "smtp.mail.yahoo.com"}


def fix_host(host, user=""):
    """常见写错的发信服务器自动纠正：smtp@gmail.com / gmail.com / 空 → smtp.gmail.com（按邮箱判断）。"""
    h = (host or "").strip().lower().replace("smtp://", "").strip("/")
    if "@" in h:                                      # smtp@gmail.com → 按 @ 后面的域名
        h = h.split("@", 1)[1]
    if h in KNOWN:
        return KNOWN[h]
    if not h and "@" in (user or ""):
        return KNOWN.get(user.split("@", 1)[1].lower().strip(), "")
    return h


def recipients(s=None, who=("owner", "cs")):
    s = s or data.settings()
    out = []
    for k in who:
        for a in str(s.get(f"{k}_email") or "").replace("；", ",").replace(";", ",").replace("，", ",").split(","):
            a = a.strip()
            if a and "@" in a and a not in out:
                out.append(a)
    return out


def configured(s=None):
    s = s or data.settings()
    return bool(s.get("smtp_host") and recipients(s))


def send(subject, text, html=None, to=None, s=None, timeout=20):
    s = s or data.settings()
    to = to or recipients(s)
    if not s.get("smtp_host"):
        raise ValueError("还没有设置发信服务器（SMTP）")
    if not to:
        raise ValueError("还没有填收件邮箱（老板邮箱 / 客服邮箱）")
    sender = (s.get("smtp_from") or s.get("smtp_user") or "").strip()
    if not sender:
        raise ValueError("请填发件邮箱")
    m = EmailMessage()
    m["Subject"] = subject
    m["From"] = formataddr(("3D 运营管理系统", sender))
    m["To"] = ", ".join(to)
    m["Message-ID"] = make_msgid()
    m.set_content(text)
    if html:
        m.add_alternative(html, subtype="html")
    host, port = fix_host(s["smtp_host"], s.get("smtp_user") or s.get("smtp_from")), int(s.get("smtp_port") or 465)
    mode = (s.get("smtp_tls") or "").lower().strip()
    # v2.22.1：端口和加密方式对不上（例如 587 选了 ssl）会报 WRONG_VERSION_NUMBER，按端口自动纠正，失败再换另一种试一次
    if port == 465:
        mode = "ssl"
    elif port in (587, 25, 2525) and mode == "ssl":
        mode = "starttls"
    elif mode not in ("ssl", "starttls", "none"):
        mode = "starttls"
    pw = "".join(str(s.get("smtp_pass") or "").split()) if "gmail" in host.lower() else (s.get("smtp_pass") or "")

    def _go(md):
        if md == "ssl":
            srv = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
        else:
            srv = smtplib.SMTP(host, port, timeout=timeout)
            if md == "starttls":
                srv.ehlo()
                srv.starttls(context=ssl.create_default_context())
                srv.ehlo()
        with srv:
            if s.get("smtp_user"):
                srv.login(s["smtp_user"].strip(), pw)
            srv.send_message(m)

    try:
        try:
            _go(mode)
        except (ssl.SSLError, smtplib.SMTPServerDisconnected, smtplib.SMTPNotSupportedError) as e1:
            other = "starttls" if mode == "ssl" else "ssl"
            try:
                _go(other)
            except (OSError, smtplib.SMTPException):
                raise e1
    except smtplib.SMTPAuthenticationError as e:
        raise ValueError("邮箱用户名或密码不对（Gmail 要用「应用专用密码」，16 位字母）") from e
    except (OSError, smtplib.SMTPException) as e:
        hint = ""
        if "Name or service not known" in str(e) or "getaddrinfo" in str(e) or "nodename" in str(e):
            hint = f"（发信服务器地址「{host}」不对：Gmail 填 smtp.gmail.com，Outlook / Hotmail 填 smtp.office365.com，Yahoo 填 smtp.mail.yahoo.com）"
        elif "WRONG_VERSION_NUMBER" in str(e):
            hint = "（端口和加密方式对不上：465 用 ssl，587 用 starttls）"
        raise ValueError(f"发邮件失败：{e}{hint}") from e
    return to
