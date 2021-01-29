from argparse import ArgumentParser

import uvicorn
from uvicorn_loguru_integration import run_uvicorn_loguru

from blobse.config import config


def main():
    parser = ArgumentParser(description='Simple small blob store over HTTP')
    sp = parser.add_subparsers(dest="action")
    sp.required = True
    p = sp.add_parser("run")
    p.add_argument(
        "-p", "--port", help="Port to run on. Default: 7330", type=int, default=7330
    )
    args = parser.parse_args()
    if args.action == 'run':
        run_uvicorn_loguru(
            uvicorn.Config(
                "blobse.app:app",
                host="0.0.0.0",
                port=args.port,
                log_level=["info", "debug"][config.debug],
                reload=config.debug,
            )
        )
    else:
        raise ValueError


if __name__ == '__main__':
    main()
