"""Safe HTML for assistant Markdown; raw Markdown remains the stored source."""

import mistune


class ChatRenderer(mistune.HTMLRenderer):
    def image(self, text: str, url: str, title: str | None = None) -> str:
        # A model-generated image URL should not trigger an automatic browser request.
        return self.link(text or '图片链接', url, title)


def render_assistant_markdown(content: str) -> str:
    parser = mistune.create_markdown(renderer=ChatRenderer(escape=True),
        plugins=['table', 'strikethrough', 'url'])
    return parser(content or '')
