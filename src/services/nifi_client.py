"""
NiFi REST API client.

Handles authentication (JWT, NiFi 2.x single-user mode) and the
most common operations needed by FlowArchitect:
  - test_connection()   — verify reachability + credentials
  - import_flow()       — POST a versioned-flow-snapshot to NiFi
  - delete_pg()         — stop + delete a process-group (cleanup)
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


class NiFiClientError(Exception):
    pass


class NiFiClient:
    """Thin wrapper around the NiFi REST API."""

    def __init__(self, url: str, username: str, password: str, timeout: int = 15):
        self.url = url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self._session = requests.Session()
        self._session.verify = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _api(self, path: str) -> str:
        return f"{self.url}/nifi-api{path}"

    def _get_token(self) -> str:
        """Obtain a JWT bearer token (NiFi 2.x single-user login)."""
        r = self._session.post(
            self._api("/access/token"),
            data={"username": self.username, "password": self.password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=self.timeout,
        )
        if not r.ok:
            raise NiFiClientError(
                f"Authentication failed [{r.status_code}]: {r.text[:400]}"
            )
        return r.text.strip()

    def _auth_headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_version(self) -> str:
        """Return NiFi version string (e.g. '2.7.2'), or 'unknown' on failure."""
        try:
            token = self._get_token()
            r = self._session.get(
                self._api("/flow/about"),
                headers=self._auth_headers(token),
                timeout=self.timeout,
            )
            if r.ok:
                return r.json().get("about", {}).get("version", "unknown")
        except Exception:
            pass
        return "unknown"

    def test_connection(self) -> tuple[bool, str]:
        """
        Check that NiFi is reachable and credentials are valid.

        Returns (True, version_string) on success,
                (False, error_message) on failure.
        """
        try:
            token = self._get_token()
            r = self._session.get(
                self._api("/flow/about"),
                headers=self._auth_headers(token),
                timeout=self.timeout,
            )
            if not r.ok:
                return False, f"HTTP {r.status_code}: {r.text[:300]}"
            version = r.json().get("about", {}).get("version", "unknown")
            return True, f"NiFi {version}"
        except NiFiClientError as e:
            return False, str(e)
        except requests.exceptions.ConnectionError:
            return False, f"Cannot connect to {self.url}"
        except Exception as e:
            return False, str(e)

    def _root_pg_id(self, token: str) -> str:
        r = self._session.get(
            self._api("/flow/process-groups/root"),
            headers=self._auth_headers(token),
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json()["processGroupFlow"]["id"]

    def find_process_group_by_name(
        self,
        name: str,
        parent_pg_id: Optional[str] = None,
    ) -> Optional[str]:
        """Return the first child process-group id with matching name."""
        target = (name or "").strip()
        if not target:
            return None
        try:
            token = self._get_token()
            if parent_pg_id is None:
                parent_pg_id = self._root_pg_id(token)
            r = self._session.get(
                self._api(f"/flow/process-groups/{parent_pg_id}"),
                headers=self._auth_headers(token),
                timeout=self.timeout,
            )
            r.raise_for_status()
            groups = (
                r.json()
                .get("processGroupFlow", {})
                .get("flow", {})
                .get("processGroups", [])
            )
            for group in groups:
                component = group.get("component", {}) or {}
                if (component.get("name") or "").strip() == target:
                    return group.get("id") or component.get("id")
        except Exception:
            logger.exception("NiFi find_process_group_by_name error")
        return None

    def import_flow(
        self,
        flow_json: dict,
        parent_pg_id: Optional[str] = None,
        position: tuple[float, float] = (0.0, 0.0),
        replace_if_exists: bool = False,
    ) -> tuple[bool, str]:
        """
        Import a NiFi flow snapshot as a new process-group.

        Parameters
        ----------
        flow_json       : dict with "flowContents" key (NiFiAdapter output)
        parent_pg_id    : where to place the group (default: canvas root)
        position        : (x, y) on canvas

        Returns (True, pg_id) on success, (False, error_message) on failure.
        """
        try:
            token = self._get_token()
            if parent_pg_id is None:
                parent_pg_id = self._root_pg_id(token)

            flow_contents = flow_json.get("flowContents", flow_json)
            name = flow_contents.get("name", "FlowArchitect Flow")

            replaced_pg_id = None
            if replace_if_exists:
                replaced_pg_id = self.find_process_group_by_name(name, parent_pg_id)
                if replaced_pg_id:
                    self.delete_pg(replaced_pg_id)

            body = {
                "revision": {"version": 0},
                "component": {
                    "name": name,
                    "position": {"x": float(position[0]), "y": float(position[1])},
                },
                "versionedFlowSnapshot": {
                    "flowContents": flow_contents,
                    "externalControllerServices": {},
                    "parameterContexts": {},
                    "flowEncodingVersion": "1.0",
                },
            }

            r = self._session.post(
                self._api(f"/process-groups/{parent_pg_id}/process-groups"),
                data=json.dumps(body),
                headers=self._auth_headers(token),
                timeout=30,
            )

            if r.status_code != 201:
                return False, f"HTTP {r.status_code}: {r.text[:600]}"

            pg_id = r.json().get("id", "")
            return True, pg_id

        except NiFiClientError as e:
            return False, str(e)
        except Exception as e:
            logger.exception("NiFi import_flow error")
            return False, str(e)

    def enable_controller_services(self, pg_id: str) -> int:
        """
        Enable all DISABLED controller services in a process-group.

        NiFi imports all controller services in DISABLED state; they must be
        explicitly enabled before processors that reference them will validate.

        Returns the number of services successfully enabled.
        """
        import time
        try:
            token = self._get_token()
            headers = self._auth_headers(token)

            def _load_services() -> list[dict]:
                response = self._session.get(
                    self._api(f"/flow/process-groups/{pg_id}/controller-services"),
                    headers=headers,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                return response.json().get("controllerServices", [])

            services = _load_services()

            enabled = 0
            for svc in services:
                component = svc.get("component", {})
                state = component.get("state") or svc.get("status", {}).get("runStatus")
                if state == "DISABLED":
                    cs_id = svc["id"]
                    revision = svc.get("revision", {"version": 0})
                    response = self._session.put(
                        self._api(f"/controller-services/{cs_id}/run-status"),
                        json={
                            "revision": revision,
                            "state": "ENABLED",
                            "disconnectedNodeAcknowledged": False,
                        },
                        headers=headers,
                        timeout=self.timeout,
                    )
                    response.raise_for_status()
                    enabled += 1

            if enabled:
                # Give NiFi time to transition services from ENABLING to ENABLED.
                for _ in range(10):
                    time.sleep(1.5)
                    services = _load_services()
                    still_disabled = any(
                        (
                            svc.get("component", {}).get("state")
                            or svc.get("status", {}).get("runStatus")
                        ) in {"DISABLED", "ENABLING"}
                        for svc in services
                    )
                    if not still_disabled:
                        break

            return enabled
        except Exception:
            logger.exception("enable_controller_services error (non-critical)")
            return 0

    def get_validation_errors(
        self,
        pg_id: str,
        retries: int = 4,
        delay: float = 1.5,
    ) -> list[dict]:
        """
        Return validation errors for all processors in a process-group.

        NiFi may still be in VALIDATING state right after import, so we retry
        a few times waiting for it to settle.

        Returns a list of dicts:
            {"name": str, "type": str, "errors": [str, ...]}
        for every processor that has at least one validation error.
        """
        import time

        try:
            token = self._get_token()
            headers = self._auth_headers(token)

            for attempt in range(retries):
                r = self._session.get(
                    self._api(f"/flow/process-groups/{pg_id}"),
                    headers=headers,
                    timeout=self.timeout,
                )
                r.raise_for_status()

                processors = (
                    r.json()
                    .get("processGroupFlow", {})
                    .get("flow", {})
                    .get("processors", [])
                )

                still_validating = any(
                    p.get("component", {}).get("validationStatus") == "VALIDATING"
                    for p in processors
                )

                if not still_validating or attempt == retries - 1:
                    results = []
                    for proc in processors:
                        component = proc.get("component", {})
                        errors = component.get("validationErrors") or []
                        if errors:
                            results.append({
                                "name": component.get("name", ""),
                                "type": component.get("type", ""),
                                "errors": errors,
                            })
                    return results

                time.sleep(delay)

        except Exception:
            logger.exception("NiFi get_validation_errors error")

        return []

    def delete_pg(self, pg_id: str) -> None:
        """Stop all processors in *pg_id*, then delete the process-group."""
        try:
            token = self._get_token()
            headers = self._auth_headers(token)
            self._session.put(
                self._api(f"/flow/process-groups/{pg_id}"),
                data=json.dumps({"id": pg_id, "state": "STOPPED"}),
                headers=headers,
                timeout=self.timeout,
            )
            r = self._session.get(
                self._api(f"/process-groups/{pg_id}"),
                headers=headers,
                timeout=self.timeout,
            )
            if r.status_code == 404:
                return
            version = r.json()["revision"]["version"]
            self._session.delete(
                self._api(f"/process-groups/{pg_id}"),
                params={"version": version},
                headers=headers,
                timeout=self.timeout,
            )
        except Exception:
            logger.exception("NiFi delete_pg error (non-critical)")
