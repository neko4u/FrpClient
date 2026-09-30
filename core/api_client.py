import requests

import requests


def _secure_url(url):
    """把 http:// 升级成 https://，其余协议一律拒绝。

    这个接口要带用户的 JWT（有效期 3 天），走明文 http 会被链路上的
    中间人直接抓走 —— 所以这里做一道兜底：老配置里若还写着 http://，
    自动改成 https:// 并打印提示，不改配置也是安全的。
    """
    url = (url or '').strip()
    if url.startswith('https://'):
        return url
    if url.startswith('http://'):
        upgraded = 'https://' + url[len('http://'):]
        print('[WARN] frp_token_api 用的是明文 http，已自动改用：%s' % upgraded)
        return upgraded
    return ''

class APIs:

    @staticmethod
    def fetch_frp_token(api_url, user_token):
        try:
            api_url = _secure_url(api_url)
            if not api_url:
                return None, '接口地址必须以 http:// 或 https:// 开头'

            headers = {

                "Authorization": f"Bearer {user_token}"
            }

            resp = requests.get(api_url, headers=headers, timeout=5)
            data = resp.json()

            if not data.get("isok"):
                return None, "接口返回失败"

            return data.get("config_token"), None

        except Exception as e:
            return None, str(e)
        
        # 留api,后续api从服务器获取并直接配置到本地
        # 用户只需要登录有权限的帐号就可以