import uvicorn

from app.config import load_env


def main() -> None:
    env = load_env()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=env.port,
        log_level=env.log_level,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
