from picsyncra.installation.maintenance import MaintenanceGate


def test_request_admission_keeps_a_mutating_request_in_the_maintenance_drain():
    from picsyncra.web.maintenance_requests import MaintenanceRequestAdmission

    gate = MaintenanceGate()
    admission = MaintenanceRequestAdmission(gate)

    lease = admission.admit("POST", "/api/products")
    assert lease is not None
    assert gate.snapshot()["active_by_kind"] == {"http_write": 1}

    gate.begin("update-1", initiator_id="admin-1")
    assert admission.admit("POST", "/api/products") is None
    lease.finish()
    assert gate.snapshot()["active_tasks"] == 0


def test_request_admission_leaves_read_and_installed_maintenance_routes_available():
    from picsyncra.web.maintenance_requests import MaintenanceRequestAdmission

    gate = MaintenanceGate()
    gate.begin("update-1", initiator_id="admin-1")
    admission = MaintenanceRequestAdmission(gate)

    assert admission.admit("GET", "/api/products") is None
    assert admission.admit("POST", "/api/installation/operations/op-1/force") is None
