class TokenHolder:
    token = ""
    expires_in = 0
    uid = ""  # fork: 登录后从 JWT 解出, 仅存内存, 不落盘

    @classmethod
    def set_token(cls, token, expires_in):
        cls.token = token
        cls.expires_in = expires_in

    @classmethod
    def set_uid(cls, uid):
        cls.uid = uid or ""

    @classmethod
    def get_token(cls):
        return cls.token

    @classmethod
    def get_uid(cls):
        return cls.uid
