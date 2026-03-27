"""Run the autonovel reader on port 9701."""

import uvicorn


def main() -> None:
    uvicorn.run("reader.app:app", host="127.0.0.1", port=9701, reload=False)


if __name__ == "__main__":
    main()
