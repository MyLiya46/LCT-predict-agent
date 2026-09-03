"""管理员端路由包（显式导入子模块，确保 main.py 可引用 .router）。"""

from app.api.admin import audits, config, datasources, llm, scenarios, tools, users

__all__ = ["audits", "config", "datasources", "llm", "scenarios", "tools", "users"]