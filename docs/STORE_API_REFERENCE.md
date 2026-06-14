# Store API Reference

Referencja publicznych metod store'ow (bez metod z prefixem `_`).

## GoalStore (`agent_core/goals/store.py`)
- `load() -> None` - laduje cele z `goals.jsonl` (MERGE semantics).
- `save() -> None` - dopisuje dirty cele do `goals.jsonl`.
- `compact() -> None` - przepisuje `goals.jsonl` do 1 rekordu per `goal.id`.
- `create(goal) -> str` - dodaje cel (PENDING/ACTIVE), zwraca `goal_id`.
- `propose(goal) -> Optional[str]` - tworzy cel PROPOSED, zwraca `goal_id` lub `None`.
- `get(goal_id) -> Optional[Goal]` - pobiera cel po ID.
- `get_all() -> List[Goal]` - zwraca wszystkie cele.
- `get_active(goal_type=None) -> List[Goal]` - zwraca aktywne cele (opcjonalnie filtrowane po typie).
- `get_proposed() -> List[Goal]` - zwraca cele PROPOSED.
- `get_children(parent_goal_id) -> List[Goal]` - zwraca dzieci wskazanego celu.
- `find_by_topic(topic) -> List[Goal]` - wyszukuje LEARNING goals po temacie.
- `set_outcome(goal_id, outcome) -> bool` - zapisuje outcome celu.
- `confirm(goal_id) -> bool` - zmienia PROPOSED -> PENDING.
- `reject(goal_id) -> bool` - zmienia PROPOSED -> ABANDONED.
- `update_status(goal_id, status, reason="manual update", actor="system") -> bool` - zmienia status celu.
- `update_progress(goal_id, progress) -> bool` - zmienia progress celu.
- `abandon_lowest() -> Optional[str]` - porzuca najnizszy priorytetowo cel.
- `expire_proposed() -> int` - oznacza przeterminowane PROPOSED jako ABANDONED.
- `reset_maintenance() -> int` - resetuje osiagniete cele maintenance.
- `seed_if_empty() -> int` - dodaje domyslne cele, jesli store jest pusty.
- `stats() -> dict` - zwraca statystyki store'a.

## BeliefStore (`agent_core/world_model/belief_store.py`)
- `load() -> int` - laduje beliefy z `beliefs.jsonl`, zwraca liczbe current beliefs.
- `save() -> None` - dopisuje dirty beliefy do `beliefs.jsonl`.
- `add(belief) -> None` - dodaje/aktualizuje belief.
- `revise(belief_id, new_confidence, new_belief_type=None, new_evidence=None) -> Optional[Belief]` - tworzy nowa rewizje beliefa.
- `get(belief_id) -> Optional[Belief]` - pobiera belief po ID.
- `get_by_entity(entity) -> List[Belief]` - pobiera current beliefs dla encji.
- `get_by_entity_type(entity_type) -> List[Belief]` - pobiera current beliefs po typie encji.
- `get_by_tag(tag) -> List[Belief]` - pobiera current beliefs po tagu.
- `get_current() -> List[Belief]` - zwraca wszystkie niesupersedowane beliefy.
- `find_by_entity_and_source(entity, source_id) -> Optional[Belief]` - deduplikacja po encja + source.
- `stats() -> Dict[str, Any]` - statystyki belief store'a.
- `compact() -> int` - compactuje `beliefs.jsonl`, zwraca liczbe usunietych linii.

## BulletinStore (`agent_core/bulletin/bulletin_store.py`)
- `post(entry) -> None` - dodaje/aktualizuje wpis bulletin.
- `create_and_post(entry_type, topic, reason_code, summary, requested_by, goal_id=None, priority=0.5, metadata=None) -> BulletinEntry` - tworzy i publikuje wpis.
- `get(entry_id) -> Optional[BulletinEntry]` - pobiera wpis po ID.
- `update_status(entry_id, status, reason="") -> bool` - zmienia status wpisu.
- `resolve(entry_id, reason="completed") -> bool` - oznacza wpis jako resolved.
- `get_open() -> List[BulletinEntry]` - zwraca otwarte wpisy.
- `get_by_type(entry_type) -> List[BulletinEntry]` - zwraca wpisy danego typu.
- `get_actionable() -> List[BulletinEntry]` - zwraca wpisy do akcji plannera.
- `find_open(topic=None, entry_type=None, goal_id=None) -> List[BulletinEntry]` - wyszukuje otwarte wpisy.
- `get_for_goal(goal_id) -> List[BulletinEntry]` - zwraca wpisy powiazane z celem.
- `prune_stale(now=None) -> int` - zamyka stale wpisy.
- `compact() -> None` - przepisuje JSONL do stanu latest.
- `stats() -> Dict[str, Any]` - statystyki bulletin store'a.

## ReminderStore (`agent_core/reminders/reminder_store.py`)
- `add(reminder) -> Reminder` - dodaje reminder.
- `get(reminder_id) -> Optional[Reminder]` - pobiera reminder po ID.
- `get_due(now=None) -> List[Reminder]` - zwraca reminders gotowe do odpalenia.
- `get_pending() -> List[Reminder]` - zwraca pending/snoozed reminders.
- `get_all() -> List[Reminder]` - zwraca wszystkie reminders.
- `update(reminder) -> None` - aktualizuje reminder i dopisuje do JSONL.
- `dismiss(reminder_id) -> Optional[Reminder]` - oznacza reminder jako dismissed.
- `snooze(reminder_id, minutes=15) -> Optional[Reminder]` - odklada reminder.
- `mark_triggered(reminder) -> None` - oznacza reminder jako triggered (i tworzy kolejny dla recurrence).
- `count() -> Dict[str, int]` - statystyki reminders.

## TodoStore (`agent_core/reminders/reminder_store.py`)
- `add(todo) -> Todo` - dodaje TODO.
- `get(todo_id) -> Optional[Todo]` - pobiera TODO po ID.
- `get_pending() -> List[Todo]` - zwraca pending TODOs.
- `get_all() -> List[Todo]` - zwraca wszystkie TODOs.
- `complete(todo_id) -> Optional[Todo]` - oznacza TODO jako done.
- `cancel(todo_id) -> Optional[Todo]` - oznacza TODO jako cancelled.
- `get_overdue(now=None) -> List[Todo]` - zwraca overdue TODOs.
- `count() -> Dict[str, int]` - statystyki TODOs.

## FetchRegistry (`agent_core/web_source/fetch_registry.py`)
- `is_fetched(url) -> bool` - sprawdza czy URL byl juz fetchowany.
- `is_topic_fetched(topic) -> bool` - sprawdza czy temat byl juz fetchowany.
- `register(url, title, source_type, output_file, char_count, topic=None) -> None` - rejestruje udany fetch.
- `get_stats() -> Dict[str, Any]` - statystyki fetch registry.
- `get_all() -> Dict[str, Dict]` - zwraca wszystkie rekordy (keyed by URL).

## TraceStore (`agent_core/tracing/trace_store.py`)
- `path -> Path` - property ze sciezka do pliku trace store.
- `record(trace) -> None` - dopisuje trace do JSONL.
- `get_recent(limit=20) -> List[Dict[str, Any]]` - zwraca ostatnie trace.
- `get_by_episode_id(episode_id) -> Optional[Dict[str, Any]]` - pobiera trace po episode ID.
- `get_by_goal_id(goal_id, limit=10) -> List[Dict[str, Any]]` - pobiera trace powiazane z goal ID.
- `get_failed(limit=10) -> List[Dict[str, Any]]` - zwraca ostatnie nieudane trace.
- `get_stats(limit=100) -> Dict[str, Any]` - agreguje statystyki trace.

## CreativeStore (`agent_core/creative/creative_store.py`)
- `save_journal_entry(entry) -> None` - zapisuje wpis creative journal.
- `load_journal() -> List[Dict]` - laduje journal entries.
- `save_meta_goal(mg) -> None` - zapisuje meta-goal.
- `load_meta_goals() -> List[Dict]` - laduje meta-goals.
- `get_recent_meta_goals(hours=24.0) -> List[Dict]` - zwraca swieze meta-goals (proposed/accepted).
- `save_conversation_memory(entry) -> None` - zapisuje memory wpis.
- `load_conversation_memories() -> List[Dict]` - laduje conversation memories.
- `get_memories_by_type(memory_type) -> List[Dict]` - filtruje memories po typie.
- `get_memories_by_importance(min_importance=0.5) -> List[Dict]` - filtruje memories po wadze.
- `save_workspace_session(session) -> None` - zapisuje podsumowanie sesji workspace.
- `load_workspace_sessions() -> List[Dict]` - laduje sesje workspace.
- `log_event(event_name, payload=None) -> None` - zapisuje event telemetry.
- `load_events(last_n=50) -> List[Dict]` - laduje ostatnie eventy.
- `record_tensions(categories) -> None` - zapisuje wykryte kategorie napiec.
- `get_tension_streak(category) -> int` - zwraca streak napiecia dla kategorii.
- `save_personality_signal(signal) -> None` - zapisuje sygnal osobowosci.
- `load_personality_signals() -> List[Dict]` - laduje sygnaly osobowosci.

## VectorStore (`agent_core/semantic/vector_store.py`)
- `load() -> int` - laduje wektory z JSONL.
- `save() -> int` - dopisuje dirty entries.
- `save_full() -> int` - przepisuje caly store do JSONL.
- `list_ids_by_namespace(namespace) -> List[str]` - zwraca IDs dla namespace.
- `add(entry_id, text, vector, metadata=None) -> bool` - dodaje/aktualizuje wpis wektorowy.
- `add_text(entry_id, text, embedding_model, metadata=None) -> bool` - embed + add.
- `add_texts_batch(entries, embedding_model) -> int` - batch embed + add.
- `remove(entry_id) -> bool` - usuwa wpis.
- `get(entry_id) -> Optional[VectorEntry]` - pobiera wpis.
- `search(query_vector, top_k=10, threshold=0.3, namespace=None) -> List[SearchResult]` - wyszukiwanie podobienstwa.
- `search_text(query, embedding_model, top_k=10, threshold=0.3, namespace=None) -> List[SearchResult]` - embed query + search.
- `count() -> int` - liczba wpisow w store.
- `get_by_namespace(namespace) -> List[VectorEntry]` - wpisy z namespace.
- `stats() -> Dict[str, Any]` - statystyki vector store'a.
