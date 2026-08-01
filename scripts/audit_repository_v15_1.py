#!/usr/bin/env python3
"""Repository-wide static audit supporting the V15.1 evidence gate."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_JSON = ROOT / "reports" / "v15_1_repository_audit.json"
REPORT_MD = ROOT / "reports" / "v15_1_repository_audit.md"

TEXT_SUFFIXES = {
    ".sol", ".js", ".py", ".yml", ".yaml", ".json", ".md", ".sh", ".txt"
}
EXCLUDED_PARTS = {"node_modules", ".git", "artifacts", "cache", "reports"}

SOURCE_REWRITE_PATTERNS = {
    "perl_in_place": re.compile(r"\bperl\s+-0?pi\b"),
    "sed_in_place": re.compile(r"\bsed\s+-i\b"),
    "python_patch_script": re.compile(r"python(?:3)?\s+scripts/patch_[\w.-]+\.py"),
}
PRIVATE_KEY_LITERAL = re.compile(r"(?<![0-9a-fA-F])0x[0-9a-fA-F]{64}(?![0-9a-fA-F])")


def iter_text_files():
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        yield path


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def main() -> None:
    files = list(iter_text_files())
    contents: dict[Path, str] = {}
    unreadable: list[str] = []
    for path in files:
        try:
            contents[path] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            unreadable.append(relative(path))

    workflows = {
        relative(path): text
        for path, text in contents.items()
        if ".github/workflows" in path.as_posix()
    }
    patch_scripts = sorted(
        relative(path)
        for path in contents
        if path.name.startswith("patch_") and path.suffix == ".py"
    )

    workflow_rewrites: list[dict[str, str]] = []
    for workflow_path, text in workflows.items():
        for name, pattern in SOURCE_REWRITE_PATTERNS.items():
            if pattern.search(text):
                workflow_rewrites.append({"workflow": workflow_path, "pattern": name})

    secret_literals: list[dict[str, str]] = []
    for path, text in contents.items():
        if path.name in {"package-lock.json"}:
            continue
        for match in PRIVATE_KEY_LITERAL.finditer(text):
            literal = match.group(0)
            # Known public hashes and zero constants can be 32 bytes. Flag only
            # contexts that look like credentials rather than every bytes32 value.
            window = text[max(0, match.start() - 80): match.end() + 80].lower()
            if any(word in window for word in ("private", "secret", "wallet", "owner_private")):
                secret_literals.append({
                    "file": relative(path),
                    "prefix": literal[:10],
                })

    strict_workflows = [
        name for name in workflows
        if name.endswith("stateful-supercycle-v8.yml")
        or name.endswith("external-revenue-v15-1-strict.yml")
    ]
    strict_rewrites = [
        item for item in workflow_rewrites if item["workflow"] in strict_workflows
    ]

    required_files = [
        "contracts/v15_1/SolverAuctionV151.sol",
        "contracts/v15_1/ExternalRevenueEngineV151.sol",
        "contracts/v15_1/RouterAdaptersV151.sol",
        "contracts/v15_1/PrivateRFQSettlementV151.sol",
        "scripts/discover_historical_victim_v15_1.js",
        "scripts/validate_external_revenue_v15_1.py",
        "test/external_revenue_v15_1_historical_polygon_fork.js",
        "docs/V15_1_REPOSITORY_AUDIT_AND_STRICT_DESIGN.md",
    ]
    required_presence = {name: (ROOT / name).is_file() for name in required_files}

    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    scripts = package.get("scripts", {})
    npm_test_runs_hardhat = "hardhat test" in str(scripts.get("test", ""))

    legacy_test = contents.get(ROOT / "test" / "external_revenue_v15_polygon_fork.js", "")
    legacy_fast_patch = contents.get(ROOT / "scripts" / "patch_external_revenue_v15_fast_mining.py", "")
    legacy_contract_mismatch = (
        'getContractFactory("OrderflowAuction"' in legacy_test
        and 'getContractFactory("SolverAuctionV15"' in legacy_fast_patch
    )
    legacy_epoch_repaired_by_patch = (
        "const epoch = await auction.currentEpoch();" in legacy_test
        and "const epoch = await auction.currentEpoch();" in legacy_fast_patch
        and "publish-start" in legacy_fast_patch
    )

    checks = {
        "all_required_v151_files_present": all(required_presence.values()),
        "strict_v151_workflows_do_not_rewrite_sources": not strict_rewrites,
        "no_credential_like_private_key_literals": not secret_literals,
        "audit_source_files_utf8_readable": not unreadable,
    }
    blocking_failures = [name for name, passed in checks.items() if not passed]

    legacy_debt = {
        "workflow_source_rewrite_references": workflow_rewrites,
        "patch_scripts": patch_scripts,
        "legacy_v15_contract_selected_only_by_runtime_patch": legacy_contract_mismatch,
        "legacy_v15_epoch_flow_repaired_only_by_runtime_patch": legacy_epoch_repaired_by_patch,
        "npm_test_does_not_run_hardhat_tests": not npm_test_runs_hardhat,
        "note": (
            "Legacy findings are retained as evidence debt and must not be used "
            "to claim V15.1 failure or success. The strict V15.1 workflow is gated separately."
        ),
    }

    verdict = "FAIL" if blocking_failures else (
        "PASS_WITH_LEGACY_DEBT" if any([
            workflow_rewrites,
            patch_scripts,
            legacy_contract_mismatch,
            legacy_epoch_repaired_by_patch,
            not npm_test_runs_hardhat,
        ]) else "PASS"
    )

    result = {
        "verdict": verdict,
        "scannedTextFiles": len(contents),
        "workflowCount": len(workflows),
        "checks": checks,
        "blockingFailures": blocking_failures,
        "requiredFilePresence": required_presence,
        "legacyDebt": legacy_debt,
        "unreadableTextFiles": unreadable,
        "credentialLikePrivateKeyLiterals": secret_literals,
    }

    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(result, indent=2), encoding="utf-8")

    lines = [
        "# V15.1 repository-wide static audit",
        "",
        f"- verdict: `{verdict}`",
        f"- scanned text files: `{len(contents)}`",
        f"- workflows: `{len(workflows)}`",
        f"- patch scripts retained as legacy debt: `{len(patch_scripts)}`",
        f"- workflow source-rewrite references: `{len(workflow_rewrites)}`",
        f"- credential-like private-key literals: `{len(secret_literals)}`",
        "",
        "## Blocking checks",
        "",
    ]
    lines.extend(
        f"- {'PASS' if passed else 'FAIL'} — `{name}`"
        for name, passed in checks.items()
    )
    lines.extend([
        "",
        "## Interpretation",
        "",
        "`PASS_WITH_LEGACY_DEBT` means the strict V15.1 path is source-immutable and",
        "contains no detected credential literal, while older experiments still retain",
        "runtime patch machinery or incomplete default test wiring. Those legacy paths",
        "are not accepted as V15.1 economic evidence.",
    ])
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    if blocking_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
