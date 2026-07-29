# API 端点文档

## 认证相关
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/auth/register` | POST | 注册用户，返回 JWT Token |
| `/api/auth/login` | POST | 登录，返回 JWT Token |

注册请求体：`{"username": "string", "password": "string", "couple_code": "string|null"}`
返回：`{"access_token": "string", "token_type": "bearer"}`

## 瞬间相关
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/moments` | GET | 获取当前用户的时间线（按日期倒序） |
| `/api/moments` | POST | 创建新瞬间 |
| `/api/moments/{id}` | DELETE | 删除指定瞬间 |

创建瞬间请求体：`{"title": "string", "content": "string", "date": "YYYY-MM-DD", "tags": ["string"], "latitude": "float|null", "longitude": "float|null", "location_name": "string|null"}`

## 纪念日相关
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/anniversaries` | GET | 获取纪念日列表（按距今天数升序） |
| `/api/anniversaries` | POST | 创建新纪念日 |

纪念日请求体：`{"name": "string", "date": "YYYY-MM-DD", "type": "love_start|first_date|proposal|wedding|custom"}`

## 上传相关
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/upload` | POST | 上传图片，返回图片 URL |

上传参数：`file` (multipart), `moment_id` (可选，关联到指定瞬间)

## 健康检查
| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 返回 `{"status": "ok"}` |
