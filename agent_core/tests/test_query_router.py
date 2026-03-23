"""Tests for OperationalQueryRouter."""

import pytest

from agent_core.introspection.query_router import (
    OperationalQueryRouter,
    ResponseMode,
)


@pytest.fixture
def router():
    return OperationalQueryRouter()


class TestQueryRouterClassify:
    def test_normal_chat(self, router):
        assert router.classify("Opowiedz mi zart") == ResponseMode.NORMAL

    def test_empty_message(self, router):
        assert router.classify("") == ResponseMode.NORMAL

    def test_short_message(self, router):
        assert router.classify("ok") == ResponseMode.NORMAL

    def test_none_safe(self, router):
        # Should not crash
        assert router.classify(None) == ResponseMode.NORMAL

    # -- Error detection --

    def test_error_blad(self, router):
        assert router.classify("Co to za blad?") == ResponseMode.GROUNDED_ERROR

    def test_error_nie_dziala(self, router):
        assert router.classify("cos nie dziala") == ResponseMode.GROUNDED_ERROR

    def test_error_crash(self, router):
        assert router.classify("Maria crash!") == ResponseMode.GROUNDED_ERROR

    def test_error_zapetla(self, router):
        assert router.classify("dlaczego sie zapetla?") == ResponseMode.GROUNDED_ERROR

    def test_error_co_sie_stalo(self, router):
        assert router.classify("co sie stalo?") == ResponseMode.GROUNDED_ERROR

    # -- Learning detection --

    def test_learning_nauka(self, router):
        assert router.classify("jak ci idzie nauka?") == ResponseMode.GROUNDED_LEARNING

    def test_learning_uczysz(self, router):
        assert router.classify("czego sie uczysz?") == ResponseMode.GROUNDED_LEARNING

    def test_learning_egzamin(self, router):
        assert router.classify("jak poszedl egzamin?") == ResponseMode.GROUNDED_LEARNING

    def test_learning_retention(self, router):
        assert router.classify("jaki masz retention?") == ResponseMode.GROUNDED_LEARNING

    # -- Planner detection --

    def test_planner_plan(self, router):
        assert router.classify("jaki plan masz?") == ResponseMode.GROUNDED_PLANNER

    def test_planner_strategia(self, router):
        assert router.classify("jaka strategia?") == ResponseMode.GROUNDED_PLANNER

    def test_planner_co_dalej(self, router):
        assert router.classify("co dalej?") == ResponseMode.GROUNDED_PLANNER

    # -- Status detection --

    def test_status_co_robisz(self, router):
        assert router.classify("co robisz?") == ResponseMode.GROUNDED_STATUS

    def test_status_status(self, router):
        assert router.classify("status") == ResponseMode.GROUNDED_STATUS

    def test_status_tryb(self, router):
        assert router.classify("jaki tryb?") == ResponseMode.GROUNDED_STATUS

    def test_status_zdrowie(self, router):
        assert router.classify("jak twoje zdrowie?") == ResponseMode.GROUNDED_STATUS

    def test_status_english(self, router):
        assert router.classify("what are you doing?") == ResponseMode.GROUNDED_STATUS

    # -- Priority: error > learning > planner > status --

    def test_error_takes_priority(self, router):
        # "blad" keyword should win over "nauka"
        assert router.classify("blad w nauce") == ResponseMode.GROUNDED_ERROR

    # -- is_grounded --

    def test_is_grounded_normal(self):
        assert OperationalQueryRouter.is_grounded(ResponseMode.NORMAL) is False

    def test_is_grounded_status(self):
        assert OperationalQueryRouter.is_grounded(ResponseMode.GROUNDED_STATUS) is True

    def test_is_grounded_error(self):
        assert OperationalQueryRouter.is_grounded(ResponseMode.GROUNDED_ERROR) is True

    def test_is_grounded_learning(self):
        assert OperationalQueryRouter.is_grounded(ResponseMode.GROUNDED_LEARNING) is True

    def test_is_grounded_planner(self):
        assert OperationalQueryRouter.is_grounded(ResponseMode.GROUNDED_PLANNER) is True
