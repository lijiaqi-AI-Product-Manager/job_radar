"""招聘正文容器提取与已确认模板污染识别；不以页面标题或导航补正文。"""

import re
from html.parser import HTMLParser

_IGNORED = {"head", "title", "script", "style", "template", "noscript", "nav", "header", "footer"}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_CONTAINERS = {"job-content", "job-desc", "job-description", "job-detail-content"}


class _Document(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = ["document", {}, []]
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = [tag, dict(attrs), []]
        self.stack[-1][2].append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1][2].append([tag, dict(attrs), []])

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1][2].append(data)


def _ignored(node):
    classes = set((node[1].get("class") or "").split())
    return node[0] in _IGNORED or node[1].get("role") == "navigation" or bool(classes & {"nav", "navbar", "footer", "menu"})


def _text(node):
    if isinstance(node, str):
        return node
    if _ignored(node):
        return ""
    return " ".join(_text(child) for child in node[2])


def _containers(node):
    if isinstance(node, str) or _ignored(node):
        return
    if set((node[1].get("class") or "").split()) & _CONTAINERS:
        yield node
        return
    for child in node[2]:
        yield from _containers(child)


def template_pollution(text):
    if not text:
        return False
    return (all(marker in text for marker in ("[v-cloak]", ":root", "PAGE_THEME"))
            or (".job-desc" in text and "font-size:" in text and "单位简介富文本" in text[:150]))


def extract_job_body(page):
    doc = _Document()
    doc.feed(page)
    containers = list(_containers(doc.root))
    text = " ".join(_text(node) for node in containers) if containers else _text(doc.root)
    text = re.sub(r"\{\{.*?\}\}", " ", text, flags=re.S)
    text = re.sub(r"\s+", " ", text).strip()
    if not containers:
        anchor = re.search(r"岗位职责|工作职责|任职要求|职位描述", text)
        if not anchor:
            return None
        text = text[anchor.start():]
    text = re.split(r"单位信息|联系方式|相关职位|版权所有", text, maxsplit=1)[0].strip()
    content = re.sub(r"岗位职责|工作职责|职位描述|岗位要求|任职要求|投递说明|其他描述", "", text)
    if not content.strip(" ：:;；,，。.!！?？、-—\t\r\n"):
        return None
    return text if text and not template_pollution(text) else None
