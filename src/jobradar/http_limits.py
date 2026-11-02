"""绝对请求预算与响应大小限制，包含有数据持续到达的慢连接。"""

import time

import httpx

DEADLINE_EXTENSION = "jobradar_deadline"
LIMIT_EXTENSION = "jobradar_response_limit"
MAX_RESPONSE_BYTES = 32 * 1024 * 1024


class RequestBudgetExceeded(RuntimeError):
    pass


class ResponseLimitExceeded(RuntimeError):
    pass


def check_deadline(deadline):
    if deadline is not None and time.monotonic() >= deadline:
        raise RequestBudgetExceeded("request budget exceeded")


class DeadlineStream(httpx.SyncByteStream):
    def __init__(self, original, deadline, *, clock=None):
        self.original, self.deadline = original, deadline
        self.clock = clock

    def check(self):
        if self.clock is None:
            check_deadline(self.deadline)
        elif self.deadline is not None and self.clock() >= self.deadline:
            raise RequestBudgetExceeded("request budget exceeded")

    def __iter__(self):
        self.check()
        for chunk in self.original:
            self.check()
            yield chunk
        self.check()

    def close(self):
        self.original.close()


def limit_response(response):
    deadline = response.request.extensions.get(DEADLINE_EXTENSION)
    limit = response.request.extensions.get(LIMIT_EXTENSION, MAX_RESPONSE_BYTES)
    if type(limit) is not int or not 0 < limit <= MAX_RESPONSE_BYTES:
        raise ResponseLimitExceeded("响应大小上限无效")
    response.stream = DeadlineStream(response.stream, deadline)
    chunks, total = [], 0
    try:
        for chunk in response.iter_bytes():
            check_deadline(deadline)
            total += len(chunk)
            if total > limit:
                raise ResponseLimitExceeded(f"响应超过大小上限（{limit}字节）")
            chunks.append(chunk)
        check_deadline(deadline)
        # 与httpx.Response.read相同的内容缓存；先限额再拼接，避免read()无限积累响应。
        response._content = b"".join(chunks)
    finally:
        response.close()
