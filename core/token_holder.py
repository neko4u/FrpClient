class TokenHolder:
    token = ""
    expires_in = 0

    @classmethod
    def set_token(cls, token, expires_in):
        cls.token = token
        cls.expires_in = expires_in

    @classmethod
    def get_token(cls):
        return cls.token