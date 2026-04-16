import requests

def fetch_frp_token(api_url, user_token):
    try:
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