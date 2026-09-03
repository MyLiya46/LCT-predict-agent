"""用用户名密码连接本地 PG（docker 内），列出 public schema 的表。"""
import asyncio

import asyncpg

DSN = "postgresql://app:app@127.0.0.1:5432/agent_platform"


async def main() -> None:
    conn = await asyncpg.connect(DSN)
    try:
        tables = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
        print(f"✅ 连接成功（{len(tables)} 张表）")
        for t in tables:
            print("  -", t["tablename"])
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
