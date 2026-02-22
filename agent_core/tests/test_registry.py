"""Tests for ModuleRegistry, CommandDispatcher, SharedContext."""

import pytest

from agent_core.registry import (
    MariaModule,
    CommandInfo,
    SharedContext,
    ModuleRegistry,
    CommandDispatcher,
)


# ====== Test Fixtures ======

class DummyModule(MariaModule):
    name = "dummy"
    description = "Test module"

    def __init__(self):
        self.initialized = False
        self.cleaned_up = False

    def init(self, ctx):
        self.ctx = ctx
        self.initialized = True
        return True

    def get_commands(self):
        return [
            CommandInfo(
                name="/dummy",
                handler=self._cmd_dummy,
                help_text="  /dummy  - test command",
                category="[TEST] DUMMY",
            ),
            CommandInfo(
                name="/dummy2",
                handler=self._cmd_dummy2,
                help_text="  /dummy2 - second test",
                category="[TEST] DUMMY",
            ),
        ]

    def _cmd_dummy(self, args):
        self.last_args = args

    def _cmd_dummy2(self, args):
        pass

    def cleanup(self):
        self.cleaned_up = True


class FailingInitModule(MariaModule):
    name = "failing"
    description = "Module that fails init"

    def init(self, ctx):
        return False


class ExceptionInitModule(MariaModule):
    name = "exception"
    description = "Module that raises during init"

    def init(self, ctx):
        raise RuntimeError("Init exploded")


class AnotherModule(MariaModule):
    name = "another"
    description = "Another test module"

    def get_commands(self):
        return [
            CommandInfo(
                name="/another",
                handler=lambda args: None,
                help_text="  /another - another command",
                category="[OTHER] ANOTHER",
            ),
        ]


# ====== SharedContext Tests ======

class TestSharedContext:
    def test_default_values(self):
        ctx = SharedContext()
        assert ctx.brain is None
        assert ctx.brain_loop is None
        assert ctx.semantic_memory is None
        assert ctx.episodic_memory is None
        assert ctx.homeostasis_core is None
        assert ctx.brain_model == "llama3.1:8b"

    def test_custom_values(self):
        ctx = SharedContext(brain="test_brain", brain_model="llama3.2:3b")
        assert ctx.brain == "test_brain"
        assert ctx.brain_model == "llama3.2:3b"

    def test_update(self):
        ctx = SharedContext()
        ctx.update(brain="new_brain", brain_model="new_model")
        assert ctx.brain == "new_brain"
        assert ctx.brain_model == "new_model"

    def test_update_ignores_unknown(self):
        ctx = SharedContext()
        ctx.update(nonexistent_field="value")
        assert not hasattr(ctx, "nonexistent_field") or ctx.__dict__.get("nonexistent_field") is None


# ====== MariaModule Tests ======

class TestMariaModule:
    def test_base_module_defaults(self):
        m = MariaModule()
        assert m.name == "unnamed"
        assert m.get_commands() == []
        assert m.get_help_lines() == []

    def test_base_module_init(self):
        m = MariaModule()
        ctx = SharedContext()
        assert m.init(ctx) is True

    def test_base_module_cleanup(self):
        m = MariaModule()
        m.cleanup()  # Should not raise


# ====== CommandInfo Tests ======

class TestCommandInfo:
    def test_creation(self):
        cmd = CommandInfo(
            name="/test",
            handler=lambda args: None,
            help_text="  /test - help",
            category="[CAT]",
        )
        assert cmd.name == "/test"
        assert cmd.help_text == "  /test - help"
        assert cmd.category == "[CAT]"
        assert callable(cmd.handler)


# ====== ModuleRegistry Tests ======

class TestModuleRegistry:
    def test_register(self):
        reg = ModuleRegistry()
        m = DummyModule()
        assert reg.register(m) is True
        assert reg.is_available("dummy")

    def test_register_duplicate(self):
        reg = ModuleRegistry()
        reg.register(DummyModule())
        assert reg.register(DummyModule()) is False

    def test_try_register_success(self):
        reg = ModuleRegistry()
        assert reg.try_register(lambda: DummyModule(), "dummy") is True
        assert reg.is_available("dummy")

    def test_try_register_import_error(self):
        reg = ModuleRegistry()

        def bad_factory():
            raise ImportError("no module")

        assert reg.try_register(bad_factory, "missing") is False
        assert not reg.is_available("missing")

    def test_try_register_general_error(self):
        reg = ModuleRegistry()

        def bad_factory():
            raise RuntimeError("broken")

        assert reg.try_register(bad_factory, "broken") is False

    def test_init_all_success(self):
        reg = ModuleRegistry()
        m = DummyModule()
        reg.register(m)
        ctx = SharedContext(brain="test")
        reg.init_all(ctx)
        assert m.initialized
        assert m.ctx.brain == "test"

    def test_init_all_removes_failed(self):
        reg = ModuleRegistry()
        reg.register(DummyModule())
        reg.register(FailingInitModule())
        ctx = SharedContext()
        reg.init_all(ctx)
        assert reg.is_available("dummy")
        assert not reg.is_available("failing")

    def test_init_all_handles_exception(self):
        reg = ModuleRegistry()
        reg.register(ExceptionInitModule())
        ctx = SharedContext()
        reg.init_all(ctx)
        assert not reg.is_available("exception")

    def test_cleanup_all(self):
        reg = ModuleRegistry()
        m = DummyModule()
        reg.register(m)
        ctx = SharedContext()
        reg.init_all(ctx)
        reg.cleanup_all()
        assert m.cleaned_up

    def test_get_module(self):
        reg = ModuleRegistry()
        m = DummyModule()
        reg.register(m)
        assert reg.get_module("dummy") is m
        assert reg.get_module("nonexistent") is None

    def test_get_all_modules_order(self):
        reg = ModuleRegistry()
        m1 = DummyModule()
        m2 = AnotherModule()
        reg.register(m1)
        reg.register(m2)
        modules = reg.get_all_modules()
        assert modules == [m1, m2]

    def test_get_status(self):
        reg = ModuleRegistry()
        reg.register(DummyModule())
        reg.try_register(lambda: (_ for _ in ()).throw(ImportError("nope")), "missing")
        status = reg.get_status()
        assert status["dummy"] == "active"
        assert "failed" in status["missing"]


# ====== CommandDispatcher Tests ======

class TestCommandDispatcher:
    def _make_dispatcher(self):
        reg = ModuleRegistry()
        m = DummyModule()
        reg.register(m)
        ctx = SharedContext()
        reg.init_all(ctx)
        return CommandDispatcher(reg), m

    def test_dispatch_known_command(self):
        disp, m = self._make_dispatcher()
        assert disp.dispatch("/dummy", ["arg1"]) is True
        assert m.last_args == ["arg1"]

    def test_dispatch_unknown_command(self):
        disp, _ = self._make_dispatcher()
        assert disp.dispatch("/nonexistent", []) is False

    def test_dispatch_case_insensitive(self):
        disp, m = self._make_dispatcher()
        assert disp.dispatch("/DUMMY", ["test"]) is True
        assert m.last_args == ["test"]

    def test_add_builtin(self):
        disp, _ = self._make_dispatcher()
        called = []
        disp.add_builtin("/builtin", lambda args: called.append(args))
        assert disp.dispatch("/builtin", ["x"]) is True
        assert called == [["x"]]

    def test_dispatch_handles_exception(self, capsys):
        reg = ModuleRegistry()

        class BrokenModule(MariaModule):
            name = "broken"
            def get_commands(self):
                return [CommandInfo("/broken", self._cmd, "", "")]
            def _cmd(self, args):
                raise ValueError("boom")

        reg.register(BrokenModule())
        reg.init_all(SharedContext())
        disp = CommandDispatcher(reg)
        assert disp.dispatch("/broken", []) is True
        output = capsys.readouterr().out
        assert "ERROR" in output

    def test_get_all_help(self):
        disp, _ = self._make_dispatcher()
        help_items = disp.get_all_help()
        assert len(help_items) >= 1
        categories = [cat for cat, _ in help_items]
        assert "[TEST] DUMMY" in categories

    def test_get_all_help_multiple_modules(self):
        reg = ModuleRegistry()
        reg.register(DummyModule())
        reg.register(AnotherModule())
        reg.init_all(SharedContext())
        disp = CommandDispatcher(reg)
        help_items = disp.get_all_help()
        categories = [cat for cat, _ in help_items]
        assert "[TEST] DUMMY" in categories
        assert "[OTHER] ANOTHER" in categories

    def test_get_command_names(self):
        disp, _ = self._make_dispatcher()
        names = disp.get_command_names()
        assert "/dummy" in names
        assert "/dummy2" in names

    def test_builtin_help(self):
        disp, _ = self._make_dispatcher()
        disp.set_builtin_help([("[INFO] BASIC", ["  /help - help"])])
        help_items = disp.get_all_help()
        categories = [cat for cat, _ in help_items]
        assert categories[0] == "[INFO] BASIC"


# ====== Help Line Generation Tests ======

class TestHelpLines:
    def test_module_help_lines(self):
        m = DummyModule()
        lines = m.get_help_lines()
        assert len(lines) == 1
        category, texts = lines[0]
        assert category == "[TEST] DUMMY"
        assert len(texts) == 2

    def test_empty_module_no_help(self):
        m = MariaModule()
        assert m.get_help_lines() == []
