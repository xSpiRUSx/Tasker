from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class OneCStaticFinding:
    check: str
    status: str
    message: str
    path: str | None = None


@dataclass(frozen=True)
class OneCStaticCheckResult:
    status: str
    findings: list[OneCStaticFinding] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(item.status == "failed" for item in self.findings)

    @property
    def warnings(self) -> bool:
        return any(item.status == "warning" for item in self.findings)


class OneCStaticChecks:
    def run(self, worktree_path: str | Path | None, changed_files: list[str], user_message: str = "") -> OneCStaticCheckResult:
        if not worktree_path:
            return OneCStaticCheckResult(status="skipped")

        root = Path(worktree_path)
        findings: list[OneCStaticFinding] = []
        xml_files = [file_name for file_name in changed_files if file_name.lower().endswith(".xml")]
        for file_name in xml_files:
            path = root / file_name
            try:
                ET.parse(path)
                findings.append(OneCStaticFinding("xml_parse", "passed", "XML parsed successfully.", file_name))
            except Exception as exc:
                findings.append(OneCStaticFinding("xml_parse", "failed", str(exc), file_name))

        epf_files = [file_name for file_name in changed_files if file_name.replace("\\", "/").startswith("src/epf/")]
        module_text = self._changed_bsl_text(root, changed_files)
        for file_name in xml_files:
            path = root / file_name
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for handler in sorted(set(re.findall(r'Action="([^"]+)"|handler="([^"]+)"', text))):
                name = next((part for part in handler if part), "")
                if name and name not in module_text:
                    findings.append(OneCStaticFinding("command_handler_presence", "warning", f"Handler `{name}` was referenced but not found in changed BSL modules.", file_name))

        if epf_files and self._looks_testing_only(user_message):
            side_effects = [token for token in ["Отправить", "Записать", "Провести", "Send", "Post"] if token in module_text]
            if side_effects:
                findings.append(OneCStaticFinding("no_send_side_effects_for_testing_tools", "warning", f"Possible side effects found: {', '.join(side_effects)}."))

        production_changes = [
            file_name
            for file_name in changed_files
            if file_name.replace("\\", "/").startswith("src/cfe/CommonModules/")
        ]
        if production_changes:
            findings.append(OneCStaticFinding("production_module_change", "warning", "Production module change requires scope review.", ", ".join(production_changes)))

        status = "failed" if any(item.status == "failed" for item in findings) else "warning" if any(item.status == "warning" for item in findings) else "passed"
        return OneCStaticCheckResult(status=status, findings=findings)

    def markdown(self, result: OneCStaticCheckResult) -> str:
        if result.status == "skipped":
            return "## 1C static checks\n\n- Status: `skipped`\n"
        lines = ["## 1C static checks", "", f"- Status: `{result.status}`"]
        for finding in result.findings or [OneCStaticFinding("static_checks", "passed", "No deterministic issues found.")]:
            suffix = f" ({finding.path})" if finding.path else ""
            lines.append(f"- {finding.check}: `{finding.status}` - {finding.message}{suffix}")
        return "\n".join(lines) + "\n"

    def _changed_bsl_text(self, root: Path, changed_files: list[str]) -> str:
        parts: list[str] = []
        for file_name in changed_files:
            if file_name.lower().endswith((".bsl", ".os")):
                path = root / file_name
                if path.exists():
                    parts.append(path.read_text(encoding="utf-8", errors="replace"))
        return "\n".join(parts)

    def _looks_testing_only(self, user_message: str) -> bool:
        text = user_message.lower()
        return any(token in text for token in ["testing", "test", "тест", "провер"])
