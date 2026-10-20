
import pytest

from acquire_research_papers.institution_profiles import InstitutionStore, validate_profile


def profile(identifier="first", **changes):
    return dict(schema_version=2, id=identifier, organization="Example University",
                mode="assisted", entry_url="https://library.example.edu/ieee", **changes)


def test_profiles_switch_without_replacing_other_profiles_or_sessions(tmp_path):
    store = InstitutionStore(tmp_path)
    store.save(profile())
    store.save(profile("second"))
    store.use("first")
    assert store.active()["id"] == "first"
    assert [p["id"] for p in store.list()] == ["first", "second"]
    assert store.browser_directory(tmp_path / "sessions", "first") != store.browser_directory(
        tmp_path / "sessions", "second")
    with pytest.raises(ValueError, match="already exists"):
        store.save(profile())


@pytest.mark.parametrize("changes", [
    {"id": "../escape"}, {"entry_url": "http://library.example.edu"},
    {"entry_url": "https://user:password@library.example.edu"},
    {"password": "never-store"}, {"credential_host": "*.example.edu"},
    {"entry_url": "https://library.example.edu/?SAMLResponse=secret"},
    {"contract": {"password": "never-store"}},
])
def test_rejects_unsafe_profiles(changes):
    value = profile()
    value.update(changes)
    with pytest.raises(ValueError):
        validate_profile(value)


def test_legacy_migration_preserves_reference_without_copying_credentials(tmp_path):
    store = InstitutionStore(tmp_path)
    legacy = {"organization": "Old University", "resourceAccessUrl":
              "https://ds.carsi.edu.cn/resource/gotoResource.php?id=example",
              "credentialHost": "login.example.edu", "carsiEntityId":
              "https://login.example.edu/idp", "usernameLabel": "Account", "passwordLabel": "Password",
              "loginButtonName": "Login", "carsiSchoolPlaceholder": "Institution",
              "carsiSearchText": "Old University", "carsiInstitution": "Old University",
              "carsiLoginButtonName": "Continue"}
    migrated = store.migrate_legacy(legacy)
    assert migrated["credential_ref"] == "legacy:ieee_institution"
    assert store.active()["id"] == "legacy-default"
    assert store.migrate_legacy(legacy) == migrated
    assert migrated["contract"] == legacy
    assert "password" not in migrated and "password" not in migrated["contract"]


def test_doctor_history_is_explicitly_historical_and_public_access_is_not_entitlement(tmp_path):
    store = InstitutionStore(tmp_path)
    store.save(profile())
    store.record_validation("first", {"download_verified": True, "access": "public",
                                      "returned_to_ieee": True})
    status = store.details()
    assert status["configured"] is True
    assert status["session"] == "unknown"
    assert status["last_validation"]["institutional_entitlement_verified"] is False
    assert status["last_validation"]["checked_at"]
    assert status["live_check"] is False


def test_profile_paths_do_not_follow_links_outside_store(tmp_path):
    store = InstitutionStore(tmp_path / "config")
    with pytest.raises(ValueError):
        store.get("CON")
    with pytest.raises(ValueError):
        store.browser_directory(tmp_path / "sessions", "..")
