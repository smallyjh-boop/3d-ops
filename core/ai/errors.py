class AIError(Exception):
    """AI 调用出错。kind：rate 限流 / timeout 超时 / network 网络 / auth 密钥 / server 服务商出错 / client 请求不对 /
    cap 能力不够（不能看图、不能出图）/ budget 到了费用上限 / config 没设置好。"""

    def __init__(self, msg="", kind="", status=0):
        super().__init__(msg)
        self.kind = kind
        self.status = status
