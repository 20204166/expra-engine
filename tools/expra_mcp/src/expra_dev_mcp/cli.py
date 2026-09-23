"""``expra-mcp`` command-line entry point.

stdout is reserved for command output (JSON/text meant to be read or piped);
all logging goes to stderr. This matters doubly for ``serve``: once a
transport starts, the MCP SDK owns stdout for protocol framing, and nothing
in this process may write to it via ``print()``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from . import _version, client_config
from .config import (
    PROJECT_LOCAL_FILENAME,
    ConfigError,
    ExpraMcpConfig,
    load_config,
    render_initial_config,
)
from .expra_adapter import gather_workspace_doctor
from .server import SERVER_NAME, build_server

logger = logging.getLogger("expra_dev_mcp")


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )


def _load_or_exit(explicit_config: Path | None) -> ExpraMcpConfig:
    try:
        return load_config(explicit_config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def cmd_serve(args: argparse.Namespace) -> int:
    cfg = _load_or_exit(args.config)
    server = build_server(cfg)
    logger.info("expra-mcp %s serving via %s (config=%s)", _version.__version__, args.transport, cfg.config_path)
    if args.transport == "stdio":
        asyncio.run(server.run_stdio_async())
    else:
        asyncio.run(server.run_streamable_http_async(host=args.host, port=args.port))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = _load_or_exit(args.config)
    result = asyncio.run(gather_workspace_doctor(cfg, server_name=SERVER_NAME, server_version=_version.__version__))
    print(json.dumps(result.model_dump(mode="json"), indent=2))
    return 1 if result.readiness == "NOT_READY" else 0


def cmd_init(args: argparse.Namespace) -> int:
    target = args.config_path or (Path.cwd() / PROJECT_LOCAL_FILENAME)
    references: dict[str, Path] = {}
    for item in args.reference or []:
        if "=" not in item:
            print(f"error: --reference must be ID=PATH, got {item!r}", file=sys.stderr)
            return 2
        ref_id, ref_path = item.split("=", 1)
        references[ref_id] = Path(ref_path).expanduser().resolve()

    toml_text = render_initial_config(
        expra_root=Path(args.expra).expanduser().resolve(),
        default_project=args.default_project,
        references=references,
    )
    target.write_text(toml_text, encoding="utf-8")
    print(f"wrote {target}")
    return cmd_doctor(argparse.Namespace(config=target))


def cmd_config_show(args: argparse.Namespace) -> int:
    cfg = _load_or_exit(args.config)
    print(cfg.model_dump_json(indent=2))
    return 0


def cmd_config_validate(args: argparse.Namespace) -> int:
    cfg = _load_or_exit(args.config)
    print(f"OK: {cfg.config_path}")
    return 0


def cmd_config_emit(args: argparse.Namespace) -> int:
    cfg = _load_or_exit(args.config)
    text = client_config.emit(args.client, cfg, scope=args.scope)
    if args.write:
        target = client_config.write_target(args.client, cfg, scope=args.scope)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"wrote {target}")
    else:
        print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="expra-mcp", description="Local development MCP server for expra-engine")
    parser.add_argument("--config", type=Path, default=None, help="explicit config file path")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    serve_p = sub.add_parser("serve", help="run the MCP server")
    serve_p.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=8000)
    serve_p.set_defaults(func=cmd_serve)

    doctor_p = sub.add_parser("doctor", help="print workspace/environment identity as JSON")
    doctor_p.set_defaults(func=cmd_doctor)

    init_p = sub.add_parser("init", help="write an initial .expra-mcp.toml and run doctor")
    init_p.add_argument("--expra", required=True, help="path to the expra-engine root")
    init_p.add_argument("--default-project", default=None)
    init_p.add_argument("--reference", action="append", metavar="ID=PATH")
    init_p.add_argument("--config-path", type=Path, default=None)
    init_p.set_defaults(func=cmd_init)

    config_p = sub.add_parser("config", help="inspect/emit configuration")
    config_sub = config_p.add_subparsers(dest="config_command", required=True)

    show_p = config_sub.add_parser("show")
    show_p.set_defaults(func=cmd_config_show)

    validate_p = config_sub.add_parser("validate")
    validate_p.set_defaults(func=cmd_config_validate)

    emit_p = config_sub.add_parser("emit")
    emit_p.add_argument("client", choices=list(client_config.SUPPORTED_CLIENTS))
    emit_p.add_argument("--scope", choices=["project", "user"], default="project")
    emit_p.add_argument("--write", action="store_true")
    emit_p.set_defaults(func=cmd_config_emit)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    exit_code = args.func(args)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
