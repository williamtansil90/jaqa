from __future__ import annotations

import re
import threading
from datetime import datetime
from typing import Any, Callable

from app.core.browser_setup import apply_env, launch_browser, new_browser_context
from app.core.js_recorder import RECORDER_JS
from app.core.models import Expectation, ExpectationResult, Step, TestCase
from app.core.storage import screenshots_dir

EmitFn = Callable[[str, dict[str, Any]], None]

STEP_TIMEOUT_MS = 15000
DEFAULT_WAIT_MS = 250
MAX_RECORDED_DELAY_MS = 180000


def _label_from_payload(data: dict[str, Any]) -> str:
    return (
        data.get("text")
        or data.get("placeholder")
        or data.get("name")
        or data.get("id")
        or data.get("selector")
        or ""
    )


def payload_to_step(data: dict[str, Any], current_url: str = "") -> Step | None:
    action = data.get("action") or data.get("type") or "click"
    if action not in {"click", "fill", "select", "check", "press", "goto"}:
        return None
    return Step(
        type=action,
        selector=data.get("selector", ""),
        value=str(data.get("value") or ""),
        url=data.get("url") or current_url,
        key=str(data.get("key") or ""),
        checked=data.get("checked"),
        tag=str(data.get("tag") or ""),
        label=_label_from_payload(data),
    )


def payload_to_expectation(data: dict[str, Any], after_step: int) -> dict[str, Any]:
    return {
        "selector": data.get("selector", ""),
        "tag": data.get("tag", ""),
        "sample_text": data.get("text") or data.get("value") or "",
        "label": _label_from_payload(data),
        "after_step": after_step,
        "input_like": (data.get("tag") or "").lower() in {"input", "textarea", "select"},
        "value": data.get("value", ""),
    }


def _matches(actual: str, expected: str, mode: str) -> bool:
    left = "" if actual is None else str(actual)
    right = "" if expected is None else str(expected)
    if mode == "equals":
        return left.strip() == right.strip()
    if mode == "regex":
        try:
            return re.search(right, left, flags=re.IGNORECASE | re.DOTALL) is not None
        except re.error:
            return False
    return right.strip().lower() in left.strip().lower()


def _new_automation_context(browser, test_case: TestCase):
    if test_case.browser_storage_state:
        return new_browser_context(browser, storage_state=test_case.browser_storage_state)
    context = new_browser_context(browser)
    if test_case.browser_cookies:
        context.add_cookies(test_case.browser_cookies)
    return context


class AutomationEngine:
    def __init__(self, emit: EmitFn) -> None:
        self.emit = emit
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._expect_mode = False
        self._expect_resync = False
        self._lock = threading.Lock()
        self._pages: list[Any] = []
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    def start_record(self, test_case: TestCase) -> None:
        if self._busy:
            raise RuntimeError("Mesin otomasi sedang berjalan.")
        self._stop.clear()
        self._expect_mode = False
        self._busy = True
        self._thread = threading.Thread(
            target=self._record_worker,
            args=(test_case,),
            daemon=True,
            name="jaqa-record",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def set_expect_mode(self, enabled: bool) -> None:
        self._expect_mode = bool(enabled)
        self._expect_resync = True

    def _sync_expect_ui(self) -> None:
        if not self._expect_resync:
            return
        self._expect_resync = False
        for page in list(self._pages):
            try:
                page.evaluate("on => window.__jaqa_set_expect_mode && window.__jaqa_set_expect_mode(on)", self._expect_mode)
            except Exception:
                pass

    def run_cases(self, cases: list[TestCase]) -> None:
        if self._busy:
            raise RuntimeError("Mesin otomasi sedang berjalan.")
        self._stop.clear()
        self._busy = True
        self._thread = threading.Thread(
            target=self._run_worker,
            args=(cases,),
            daemon=True,
            name="jaqa-run",
        )
        self._thread.start()

    def _emit(self, kind: str, **payload: Any) -> None:
        try:
            self.emit(kind, payload)
        except Exception:
            pass

    def _record_worker(self, test_case: TestCase) -> None:
        apply_env()
        last_url = ""
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = launch_browser(playwright)
                context = _new_automation_context(browser, test_case)
                context.expose_function("__jaqa_action", self._on_action)
                context.expose_function("__jaqa_expect", self._on_expect)
                context.expose_function("__jaqa_toggle_expect", self._on_toggle_expect)
                context.expose_function("__jaqa_stop_record", self._on_stop_record)
                context.add_init_script(RECORDER_JS)
                page = context.new_page()
                with self._lock:
                    self._pages = [page]

                def on_page(new_page) -> None:
                    with self._lock:
                        self._pages.append(new_page)
                    try:
                        new_page.evaluate(RECORDER_JS)
                        new_page.evaluate(
                            "on => window.__jaqa_set_expect_mode && window.__jaqa_set_expect_mode(on)",
                            self._expect_mode,
                        )
                    except Exception:
                        pass

                context.on("page", on_page)

                start_url = test_case.url.strip()
                if start_url:
                    if not re.match(r"^https?://", start_url, flags=re.I):
                        start_url = "https://" + start_url
                    page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
                    last_url = page.url
                    self._emit("action", step=Step(type="goto", url=page.url, label=page.url).to_dict())

                try:
                    page.evaluate(RECORDER_JS)
                except Exception:
                    pass

                self._emit("record_started", url=page.url)

                while not self._stop.is_set():
                    try:
                        self._sync_expect_ui()
                        current = page.url
                        if current and current != last_url:
                            last_url = current
                            self._emit(
                                "action",
                                step=Step(type="goto", url=current, label=current).to_dict(),
                            )
                        page.wait_for_timeout(200)
                    except Exception:
                        if self._stop.is_set():
                            break
                        page.wait_for_timeout(200)

                try:
                    browser.close()
                except Exception:
                    pass
            self._emit("record_stopped")
        except Exception as exc:
            self._emit("error", message=f"Gagal merekam: {exc}")
        finally:
            with self._lock:
                self._pages = []
            self._busy = False
            self._expect_mode = False

    def _on_action(self, data: dict[str, Any]) -> None:
        if self._stop.is_set() or self._expect_mode:
            return
        url = ""
        pages = list(self._pages)
        if pages:
            try:
                url = pages[-1].url
            except Exception:
                url = ""
        step = payload_to_step(data, url)
        if step:
            self._emit("action", step=step.to_dict())

    def _on_expect(self, data: dict[str, Any]) -> None:
        if self._stop.is_set():
            return
        self._emit("expect_pick", payload=data)

    def _on_toggle_expect(self, enabled: bool) -> None:
        if self._stop.is_set():
            return
        self._expect_mode = bool(enabled)
        self._expect_resync = True
        self._emit("expect_mode_changed", enabled=self._expect_mode)

    def _on_stop_record(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        self._emit("record_stop_requested")

    def _run_worker(self, cases: list[TestCase]) -> None:
        apply_env()
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = launch_browser(playwright)
                for test_case in cases:
                    if self._stop.is_set():
                        self._emit("run_aborted")
                        break
                    self._run_one(browser, test_case)
                try:
                    browser.close()
                except Exception:
                    pass
            self._emit("run_finished")
        except Exception as exc:
            self._emit("error", message=f"Gagal menjalankan test: {exc}")
            self._emit("run_finished")
        finally:
            with self._lock:
                self._pages = []
            self._busy = False

    def _run_one(self, browser, test_case: TestCase) -> None:
        self._emit("case_started", case_id=test_case.id, no_tc=test_case.no_tc)
        notes: list[str] = []
        results: list[ExpectationResult] = []
        context = None
        page = None
        try:
            context = _new_automation_context(browser, test_case)
            page = context.new_page()
            with self._lock:
                self._pages = [page]

            if not test_case.steps:
                raise RuntimeError("Belum ada rekaman langkah. Rekam test case terlebih dahulu.")

            pending = list(test_case.expectations)
            for index, step in enumerate(test_case.steps, start=1):
                if self._stop.is_set():
                    raise RuntimeError("Dibatalkan pengguna.")
                if step.enabled:
                    self._execute_step(page, step)
                due = [item for item in pending if item.after_step and item.after_step <= index]
                for expectation in due:
                    if expectation.enabled:
                        results.append(self._check_expectation(page, test_case, expectation))
                    pending.remove(expectation)

            for expectation in pending:
                if self._stop.is_set():
                    raise RuntimeError("Dibatalkan pengguna.")
                if expectation.enabled:
                    results.append(self._check_expectation(page, test_case, expectation))

            failed = [item for item in results if item.status == "NOK"]
            if failed:
                status = "NOK"
                notes = [item.reason for item in failed if item.reason]
            else:
                status = "OK"
                if test_case.expectations:
                    notes = ["Semua expected result sesuai."]
                else:
                    notes = ["Langkah berhasil dijalankan (tidak ada expected result)."]
        except Exception as exc:
            status = "NOK"
            notes = [str(exc)]
            if page is not None:
                shot = self._screenshot(page, test_case, "error")
                if shot:
                    notes.append(f"Screenshot: {shot}")
        finally:
            try:
                if context is not None:
                    context.close()
            except Exception:
                pass

        self._emit(
            "case_finished",
            case_id=test_case.id,
            status=status,
            notes=" | ".join(notes),
            last_run_at=datetime.now().isoformat(timespec="seconds"),
            expectation_results=[item.to_dict() for item in results],
        )

    def _execute_step(self, page, step: Step) -> None:
        timeout = STEP_TIMEOUT_MS
        if step.type == "goto":
            url = (step.url or step.value or "").strip()
            if url:
                if not re.match(r"^https?://", url, flags=re.I):
                    url = "https://" + url
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            return
        if step.type == "wait":
            page.wait_for_timeout(max(0, int(step.value or step.delay_ms or DEFAULT_WAIT_MS)))
            return
        if not step.selector:
            raise RuntimeError(f"Langkah {step.type} tidak memiliki selector.")

        locator = page.locator(step.selector).first
        locator.wait_for(state="visible", timeout=timeout)
        if step.type == "click":
            locator.click(timeout=timeout)
        elif step.type == "fill":
            locator.fill(step.value, timeout=timeout)
        elif step.type == "select":
            locator.select_option(step.value, timeout=timeout)
        elif step.type == "check":
            locator.set_checked(bool(step.checked), timeout=timeout)
        elif step.type == "press":
            if step.value:
                try:
                    locator.fill(step.value, timeout=timeout)
                except Exception:
                    pass
            locator.press(step.key or "Enter", timeout=timeout)
        else:
            raise RuntimeError(f"Tipe langkah tidak dikenali: {step.type}")
        pause = step.delay_ms if step.delay_ms and step.delay_ms > 0 else DEFAULT_WAIT_MS
        page.wait_for_timeout(int(pause))

    def _check_expectation(self, page, test_case: TestCase, expectation: Expectation) -> ExpectationResult:
        label = expectation.label or expectation.selector
        expected = expectation.expected_value
        try:
            locator = page.locator(expectation.selector).first
            count = page.locator(expectation.selector).count()
            if count == 0:
                shot = self._screenshot(page, test_case, expectation.id)
                return ExpectationResult(
                    expectation_id=expectation.id,
                    status="NOK",
                    expected=expected,
                    actual="",
                    reason=f"{label}: elemen tidak ditemukan ({expectation.selector}).",
                    label=label,
                )

            if expectation.kind == "visible":
                visible = locator.is_visible()
                actual = "true" if visible else "false"
                want = (expected or "true").strip().lower() in {"1", "true", "yes", "ya", "visible"}
                ok = visible if want else (not visible)
                reason = "" if ok else f"{label}: visibilitas aktual={actual}, diharapkan={expected or 'terlihat'}."
                if not ok:
                    self._screenshot(page, test_case, expectation.id)
                return ExpectationResult(
                    expectation_id=expectation.id,
                    status="OK" if ok else "NOK",
                    expected=expected or "terlihat",
                    actual=actual,
                    reason=reason,
                    label=label,
                )

            if expectation.kind == "checked":
                checked = bool(locator.is_checked())
                actual = "true" if checked else "false"
                want = (expected or "true").strip().lower() in {"1", "true", "yes", "ya"}
                ok = checked == want
                reason = "" if ok else f"{label}: checked aktual={actual}, diharapkan={want}."
                return ExpectationResult(
                    expectation_id=expectation.id,
                    status="OK" if ok else "NOK",
                    expected=str(want),
                    actual=actual,
                    reason=reason,
                    label=label,
                )

            if expectation.kind == "value":
                actual = locator.input_value(timeout=STEP_TIMEOUT_MS)
            elif expectation.kind == "attribute":
                actual = locator.get_attribute(expectation.attribute) or ""
            else:
                actual = locator.inner_text(timeout=STEP_TIMEOUT_MS)

            actual_norm = re.sub(r"\s+", " ", str(actual)).strip()
            ok = _matches(actual_norm, expected, expectation.match)
            reason = ""
            if not ok:
                reason = (
                    f"{label}: aktual '{actual_norm}' tidak {expectation.match} "
                    f"nilai diharapkan '{expected}'."
                )
                self._screenshot(page, test_case, expectation.id)
            return ExpectationResult(
                expectation_id=expectation.id,
                status="OK" if ok else "NOK",
                expected=expected,
                actual=actual_norm,
                reason=reason,
                label=label,
            )
        except Exception as exc:
            self._screenshot(page, test_case, expectation.id)
            return ExpectationResult(
                expectation_id=expectation.id,
                status="NOK",
                expected=expected,
                actual="",
                reason=f"{label}: gagal menilai expected — {exc}",
                label=label,
            )

    def _screenshot(self, page, test_case: TestCase, suffix: str) -> str:
        try:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_tc = re.sub(r"[^\w\-]+", "_", test_case.no_tc or test_case.id)
            path = screenshots_dir() / f"{safe_tc}_{suffix}_{stamp}.png"
            page.screenshot(path=str(path), full_page=True)
            return str(path)
        except Exception:
            return ""
