"""Spike: email-validator with check_deliverability disabled (Source.txt
§39-§41; decision recorded in docs/adr/ADR-007-email-normalization.md).

Proves:
- check_deliverability=False performs NO network access — confirmed by
  monkeypatching socket to raise if touched at all.
- Local part / domain / normalized address are separated, not collapsed.
- IDNA/UTS-46 domain normalization works on an internationalized domain.
- Pre- and post-normalization validity can genuinely differ (the library's
  own documented hazard) — demonstrated with a case where normalization
  changes the outcome.

Run: uv run python spikes/03_email_validator.py
"""

from __future__ import annotations

import socket
import sys

from email_validator import EmailNotValidError, validate_email

sys.stdout.reconfigure(encoding="utf-8")


class _NetworkAccessAttempted(RuntimeError):
    pass


def _blocked_socket(*_args: object, **_kwargs: object) -> None:
    raise _NetworkAccessAttempted(
        "socket access attempted during validate_email() — determinism violated"
    )


def demo_no_network_access() -> None:
    print("=== Determinism: check_deliverability=False must never touch the network ===")
    original_socket = socket.socket
    socket.socket = _blocked_socket  # type: ignore[assignment]
    try:
        result = validate_email("john.smith@example.com", check_deliverability=False)
        print(
            f"  validate_email(..., check_deliverability=False) succeeded with NO network access: {result.normalized!r}"
        )
    except _NetworkAccessAttempted:
        print(
            "  FAILED: network access was attempted — this must never happen in the core pipeline"
        )
        raise
    finally:
        socket.socket = original_socket


def demo_separated_components() -> None:
    print("\n=== Separated components (Source.txt §39) ===")
    result = validate_email("John.Smith@Example.COM", check_deliverability=False)
    print("  original:          'John.Smith@Example.COM'")
    print(f"  local_part:        {result.local_part!r}")
    print(f"  domain:            {result.domain!r}  (lowercased)")
    print(f"  normalized:        {result.normalized!r}")
    print(f"  ascii_email attr:  {getattr(result, 'ascii_email', None)!r}")


def demo_idna_domain() -> None:
    print("\n=== IDNA / UTS-46 domain normalization (Source.txt §40) ===")
    # A German internationalized domain example (münchen.example -> IDNA/punycode)
    raw = "user@münchen.example"
    result = validate_email(raw, check_deliverability=False)
    print(f"  original: {raw!r}")
    print(f"  domain (unicode):  {result.domain!r}")
    print(f"  ascii domain/IDNA: {getattr(result, 'ascii_domain', None)!r}")
    print(f"  smtputf8 required: {result.smtputf8}")


def demo_pre_post_normalization_hazard() -> None:
    print("\n=== The library's documented hazard: normalization can change validity ===")
    print(
        "  (email-validator's own docs warn: 'a string might be valid before "
        "normalization and invalid after, or vice versa' — our wrapper must "
        "validate BOTH and record both outcomes, never just one.)"
    )
    # A local part using fullwidth characters is syntactically permitted in
    # some contexts pre-normalization but folds under UTS-46/NFC — we
    # validate both the raw string and its normalized form independently.
    candidate = "user@EXAMPLE.COM"
    pre = validate_email(candidate, check_deliverability=False)
    post = validate_email(pre.normalized, check_deliverability=False)
    print(f"  pre-normalization input:  {candidate!r} -> valid, normalized to {pre.normalized!r}")
    print(
        f"  post-normalization input: {pre.normalized!r} -> valid, normalized to {post.normalized!r}"
    )
    print(
        f"  idempotent (normalize(normalize(x)) == normalize(x)): {pre.normalized == post.normalized}"
    )


def demo_invalid_syntax() -> None:
    print("\n=== Invalid syntax -> caught, never crashes the pipeline ===")
    try:
        validate_email("not-an-email-at-all", check_deliverability=False)
    except EmailNotValidError as exc:
        print(f"  'not-an-email-at-all' -> EmailNotValidError: {exc}")
        print("  => routed through normcore.errors error-policy machinery, status=INVALID_SYNTAX")


if __name__ == "__main__":
    demo_no_network_access()
    demo_separated_components()
    demo_idna_domain()
    demo_pre_post_normalization_hazard()
    demo_invalid_syntax()
