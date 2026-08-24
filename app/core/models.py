from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


Status = Literal["", "OK", "NOK", "RUNNING"]
MatchMode = Literal["equals", "contains", "regex"]
CheckKind = Literal["text", "value", "visible", "attribute", "checked"]
StepType = Literal["goto", "click", "fill", "select", "check", "press", "wait"]


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _as_enabled(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"0", "false", "no", "tidak", "disable", "disabled", "off"}:
        return False
    if text in {"1", "true", "yes", "ya", "enable", "enabled", "on"}:
        return True
    return default


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def format_delay(ms: int) -> str:
    value = max(0, int(ms or 0))
    if value <= 0:
        return "0 ms"
    if value < 1000:
        return f"{value} ms"
    seconds = value / 1000
    if seconds < 10:
        return f"{seconds:.2f} dtk"
    return f"{seconds:.1f} dtk"


STEP_TYPE_LABELS = {
    "goto": "Buka URL",
    "click": "Klik",
    "fill": "Isi",
    "select": "Pilih",
    "check": "Centang",
    "press": "Tekan tombol",
    "wait": "Delay / Tunggu",
}

TC_LIST_COLUMNS: tuple[tuple[str, str], ...] = (
    ("aktif", "Active"),
    ("no_tc", "NO. TC"),
    ("deskripsi", "Description"),
    ("aplikasi", "Application"),
    ("url", "URL"),
    ("username", "Username"),
    ("password", "Password"),
    ("expected_result", "Expectation"),
    ("expectation", "Expected Result"),
    ("status", "Status"),
    ("notes", "Notes"),
)

TC_FIELD_LABELS = {key: label for key, label in TC_LIST_COLUMNS}

TC_FILE_FIELDS = (
    "aktif",
    "no_tc",
    "deskripsi",
    "aplikasi",
    "url",
    "username",
    "password",
    "expected_result",
    "notes",
)

STEP_LIST_COLUMNS: tuple[tuple[str, str], ...] = (
    ("aktif", "Active"),
    ("no", "#"),
    ("tipe", "Type"),
    ("ket", "Step"),
    ("delay", "Delay"),
    ("selector", "Selector"),
    ("nilai", "Value"),
)

STEP_EXPORT_FIELDS: tuple[tuple[str, str], ...] = (
    ("no_tc", "NO. TC"),
    ("urutan", "#"),
    ("enabled", "Active"),
    ("type", "Type"),
    ("label", "Step"),
    ("selector", "Selector"),
    ("value", "Value"),
    ("url", "URL"),
    ("key", "Key"),
    ("checked", "Checked"),
    ("delay_ms", "Delay"),
    ("tag", "Tag"),
    ("id", "ID"),
)

EXPECT_LIST_COLUMNS: tuple[tuple[str, str], ...] = (
    ("aktif", "Active"),
    ("no", "#"),
    ("label", "Label"),
    ("kind", "Type"),
    ("match", "Comparison"),
    ("nilai", "Expected Value"),
    ("after", "Check After"),
)

EXPECT_EXPORT_FIELDS: tuple[tuple[str, str], ...] = (
    ("no_tc", "NO. TC"),
    ("urutan", "#"),
    ("enabled", "Active"),
    ("label", "Label"),
    ("selector", "Selector"),
    ("kind", "Type"),
    ("match", "Comparison"),
    ("expected_value", "Expected Value"),
    ("attribute", "Attribute"),
    ("after_step", "Check After"),
    ("tag", "Tag"),
    ("sample_text", "Sample"),
    ("id", "ID"),
)


@dataclass
class Step:
    type: StepType
    id: str = field(default_factory=_new_id)
    selector: str = ""
    value: str = ""
    url: str = ""
    key: str = ""
    checked: bool | None = None
    tag: str = ""
    label: str = ""
    delay_ms: int = 0
    timestamp: str = field(default_factory=_now_iso)
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "selector": self.selector,
            "value": self.value,
            "url": self.url,
            "key": self.key,
            "checked": self.checked,
            "tag": self.tag,
            "label": self.label,
            "delay_ms": self.delay_ms,
            "timestamp": self.timestamp,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Step:
        delay = data.get("delay_ms")
        if delay is None:
            delay = data.get("delay") or 0
        return cls(
            id=data.get("id") or _new_id(),
            type=data.get("type", "click"),
            selector=data.get("selector", ""),
            value=data.get("value", ""),
            url=data.get("url", ""),
            key=data.get("key", ""),
            checked=data.get("checked"),
            tag=data.get("tag", ""),
            label=data.get("label", ""),
            delay_ms=max(0, int(delay or 0)),
            timestamp=data.get("timestamp", _now_iso()),
            enabled=_as_enabled(data.get("enabled", True)),
        )

    def type_label(self) -> str:
        return STEP_TYPE_LABELS.get(self.type, self.type)

    def summary(self) -> str:
        if self.type == "goto":
            return f"Buka {self.url}"
        if self.type == "click":
            return f"Klik {self.label or self.selector}"
        if self.type == "fill":
            return f"Isi {self.label or self.selector} = {self.value}"
        if self.type == "select":
            return f"Pilih {self.label or self.selector} = {self.value}"
        if self.type == "check":
            state = "centang" if self.checked else "hapus centang"
            return f"{state.title()} {self.label or self.selector}"
        if self.type == "press":
            return f"Tekan {self.key} pada {self.label or self.selector}"
        if self.type == "wait":
            return f"Tunggu {format_delay(int(self.value or 0))}"
        return self.type

    def duplicate(self) -> Step:
        clone = Step.from_dict(self.to_dict())
        clone.id = _new_id()
        return clone


@dataclass
class Expectation:
    id: str = field(default_factory=_new_id)
    selector: str = ""
    kind: CheckKind = "text"
    attribute: str = ""
    match: MatchMode = "contains"
    expected_value: str = ""
    label: str = ""
    after_step: int = 0
    tag: str = ""
    sample_text: str = ""
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "selector": self.selector,
            "kind": self.kind,
            "attribute": self.attribute,
            "match": self.match,
            "expected_value": self.expected_value,
            "label": self.label,
            "after_step": self.after_step,
            "tag": self.tag,
            "sample_text": self.sample_text,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Expectation:
        return cls(
            id=data.get("id") or _new_id(),
            selector=data.get("selector", ""),
            kind=data.get("kind", "text"),
            attribute=data.get("attribute", ""),
            match=data.get("match", "contains"),
            expected_value=data.get("expected_value", ""),
            label=data.get("label", ""),
            after_step=int(data.get("after_step") or 0),
            tag=data.get("tag", ""),
            sample_text=data.get("sample_text", ""),
            enabled=_as_enabled(data.get("enabled", True)),
        )

    def summary(self) -> str:
        target = self.label or self.selector
        if self.kind == "visible":
            return f"{target} terlihat"
        if self.kind == "checked":
            return f"{target} tercentang = {self.expected_value}"
        if self.kind == "attribute":
            return f"{target} @{self.attribute} {self.match} '{self.expected_value}'"
        return f"{target} {self.kind} {self.match} '{self.expected_value}'"

    def duplicate(self) -> Expectation:
        clone = Expectation.from_dict(self.to_dict())
        clone.id = _new_id()
        return clone


@dataclass
class ExpectationResult:
    expectation_id: str
    status: Status
    expected: str = ""
    actual: str = ""
    reason: str = ""
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "expectation_id": self.expectation_id,
            "status": self.status,
            "expected": self.expected,
            "actual": self.actual,
            "reason": self.reason,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExpectationResult:
        return cls(
            expectation_id=data.get("expectation_id", ""),
            status=data.get("status", ""),
            expected=data.get("expected", ""),
            actual=data.get("actual", ""),
            reason=data.get("reason", ""),
            label=data.get("label", ""),
        )


@dataclass
class TestCase:
    id: str = field(default_factory=_new_id)
    no_tc: str = ""
    deskripsi: str = ""
    aplikasi: str = ""
    url: str = ""
    username: str = ""
    password: str = ""
    expected_result: str = ""
    steps: list[Step] = field(default_factory=list)
    expectations: list[Expectation] = field(default_factory=list)
    status: Status = ""
    notes: str = ""
    last_run_at: str = ""
    expectation_results: list[ExpectationResult] = field(default_factory=list)
    enabled: bool = True
    browser_cookies: list[dict[str, Any]] = field(default_factory=list)
    browser_storage_state: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "no_tc": self.no_tc,
            "deskripsi": self.deskripsi,
            "aplikasi": self.aplikasi,
            "url": self.url,
            "username": self.username,
            "password": self.password,
            "expected_result": self.expected_result,
            "enabled": self.enabled,
            "steps": [s.to_dict() for s in self.steps],
            "expectations": [e.to_dict() for e in self.expectations],
            "status": self.status,
            "notes": self.notes,
            "last_run_at": self.last_run_at,
            "expectation_results": [r.to_dict() for r in self.expectation_results],
            "browser_cookies": self.browser_cookies,
            "browser_storage_state": self.browser_storage_state,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestCase:
        return cls(
            id=data.get("id") or _new_id(),
            no_tc=data.get("no_tc", ""),
            deskripsi=data.get("deskripsi", ""),
            aplikasi=data.get("aplikasi", ""),
            url=data.get("url", ""),
            username=data.get("username", ""),
            password=data.get("password", ""),
            expected_result=data.get("expected_result", ""),
            steps=[Step.from_dict(s) for s in data.get("steps") or []],
            expectations=[Expectation.from_dict(e) for e in data.get("expectations") or []],
            status=data.get("status", "") or "",
            notes=data.get("notes", ""),
            last_run_at=data.get("last_run_at", ""),
            expectation_results=[
                ExpectationResult.from_dict(r) for r in data.get("expectation_results") or []
            ],
            enabled=_as_enabled(data.get("enabled", True)),
            browser_cookies=[dict(item) for item in data.get("browser_cookies") or []],
            browser_storage_state=dict(data.get("browser_storage_state") or {}),
        )

    def reset_run(self) -> None:
        self.status = ""
        self.notes = ""
        self.last_run_at = ""
        self.expectation_results = []

    def duplicate(self, with_steps: bool = False) -> TestCase:
        suffix = "-copy"
        base_no = self.no_tc or "TC"
        if with_steps:
            clone = TestCase.from_dict(self.to_dict())
            clone.id = _new_id()
            clone.no_tc = f"{base_no}{suffix}"
            clone.status = ""
            clone.notes = ""
            clone.last_run_at = ""
            clone.expectation_results = []
            for step in clone.steps:
                step.id = _new_id()
            for item in clone.expectations:
                item.id = _new_id()
            return clone
        return TestCase(
            no_tc=f"{base_no}{suffix}",
            deskripsi=self.deskripsi,
            aplikasi=self.aplikasi,
            url=self.url,
            username=self.username,
            password=self.password,
            expected_result=self.expected_result,
            enabled=self.enabled,
            browser_cookies=[dict(item) for item in self.browser_cookies],
            browser_storage_state=dict(self.browser_storage_state),
        )


@dataclass
class TestSuite:
    version: str = "1.0"
    name: str = "JAQA Suite"
    test_cases: list[TestCase] = field(default_factory=list)
    exported_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "app": "JAQA",
            "version": self.version,
            "name": self.name,
            "exported_at": self.exported_at or _now_iso(),
            "test_cases": [tc.to_dict() for tc in self.test_cases],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestSuite:
        cases_raw = data.get("test_cases") or data.get("testCases") or []
        return cls(
            version=str(data.get("version", "1.0")),
            name=data.get("name", "JAQA Suite"),
            test_cases=[TestCase.from_dict(tc) for tc in cases_raw],
            exported_at=data.get("exported_at", ""),
        )

    def index_of(self, tc_id: str) -> int:
        for i, tc in enumerate(self.test_cases):
            if tc.id == tc_id:
                return i
        return -1
