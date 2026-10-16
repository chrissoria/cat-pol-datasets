import local_steps
import run_ca_cities
import run_ca_counties


def test_a_step_that_fails_or_panics_stops_only_itself(monkeypatch):
    class PanicException(BaseException):
        pass

    ran = []

    def module(name):
        class Step:
            @staticmethod
            def main(argv):
                ran.append(name)
                if name == "panics":
                    raise PanicException("Python API call failed")
                if name == "exits":
                    raise SystemExit(2)
                return 1 if name == "fails" else 0
        return Step

    monkeypatch.setattr(local_steps.importlib, "import_module", module)
    steps = [(name, [], name) for name in ("panics", "exits", "fails", "works")]
    assert local_steps.run("test", steps) == 1
    assert ran == ["panics", "exits", "fails", "works"]
    monkeypatch.setattr(local_steps.importlib, "import_module", lambda name: module("works"))
    assert local_steps.run("test", [("works", [], "works")]) == 0


def test_the_county_and_city_routines_run_their_own_steps(monkeypatch):
    seen = []
    monkeypatch.setattr(local_steps, "run", lambda name, steps: seen.append((name, list(steps))) or 0)
    assert run_ca_counties.main(["--minutes", "45"]) == 0 and run_ca_cities.main([]) == 0
    (counties, county_steps), (cities, city_steps) = seen
    assert counties == "ca-counties" and county_steps[-1][:2] == ("build_ca_county_boards", ["--read", "--minutes", "45"])
    assert cities == "ca-cities" and [module for module, _, _ in city_steps].count("build_legistar_council") == 3
