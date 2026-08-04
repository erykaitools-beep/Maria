# Store API Reference

Reference of the public store methods (excluding methods with a `_` prefix).

## GoalStore (`agent_core/goals/store.py`)
- `load() -> None` - loads goals from `goals.jsonl` (MERGE semantics).
- `save() -> None` - appends dirty goals to `goals.jsonl`.
- `compact() -> None` - rewrites `goals.jsonl` down to 1 record per `goal.id`.
- `create(goal) -> str` - adds a goal (PENDING/ACTIVE), returns `goal_id`.
- `propose(goal) -> Optional[str]` - creates a PROPOSED goal, returns `goal_id` or `None`.
- `get(goal_id) -> Optional[Goal]` - fetches a goal by ID.
- `get_all() -> List[Goal]` - returns all goals.
- `get_active(goal_type=None) -> List[Goal]` - returns active goals (optionally filtered by type).
- `get_proposed() -> List[Goal]` - returns PROPOSED goals.
- `get_children(parent_goal_id) -> List[Goal]` - returns the children of the given goal.
- `find_by_topic(topic) -> List[Goal]` - looks up LEARNING goals by topic.
- `set_outcome(goal_id, outcome) -> bool` - stores the goal outcome.
- `confirm(goal_id) -> bool` - changes PROPOSED -> PENDING.
- `reject(goal_id) -> bool` - changes PROPOSED -> ABANDONED.
- `update_status(goal_id, status, reason="manual update", actor="system") -> bool` - changes the goal status.
- `update_progress(goal_id, progress) -> bool` - changes the goal progress.
- `abandon_lowest() -> Optional[str]` - abandons the lowest-priority goal.
- `expire_proposed() -> int` - marks expired PROPOSED goals as ABANDONED.
- `reset_maintenance() -> int` - resets achieved maintenance goals.
- `seed_if_empty() -> int` - adds default goals if the store is empty.
- `stats() -> dict` - returns store statistics.

## BeliefStore (`agent_core/world_model/belief_store.py`)
- `load() -> int` - loads beliefs from `beliefs.jsonl`, returns the number of current beliefs.
- `save() -> None` - appends dirty beliefs to `beliefs.jsonl`.
- `add(belief) -> None` - adds/updates a belief.
- `revise(belief_id, new_confidence, new_belief_type=None, new_evidence=None) -> Optional[Belief]` - creates a new revision of a belief.
- `get(belief_id) -> Optional[Belief]` - fetches a belief by ID.
- `get_by_entity(entity) -> List[Belief]` - fetches current beliefs for an entity.
- `get_by_entity_type(entity_type) -> List[Belief]` - fetches current beliefs by entity type.
- `get_by_tag(tag) -> List[Belief]` - fetches current beliefs by tag.
- `get_current() -> List[Belief]` - returns all non-superseded beliefs.
- `find_by_entity_and_source(entity, source_id) -> Optional[Belief]` - deduplication by entity + source.
- `stats() -> Dict[str, Any]` - belief store statistics.
- `compact() -> int` - compacts `beliefs.jsonl`, returns the number of removed lines.

## BulletinStore (`agent_core/bulletin/bulletin_store.py`)
- `post(entry) -> None` - adds/updates a bulletin entry.
- `create_and_post(entry_type, topic, reason_code, summary, requested_by, goal_id=None, priority=0.5, metadata=None) -> BulletinEntry` - creates and posts an entry.
- `get(entry_id) -> Optional[BulletinEntry]` - fetches an entry by ID.
- `update_status(entry_id, status, reason="") -> bool` - changes the entry status.
- `resolve(entry_id, reason="completed") -> bool` - marks an entry as resolved.
- `get_open() -> List[BulletinEntry]` - returns open entries.
- `get_by_type(entry_type) -> List[BulletinEntry]` - returns entries of the given type.
- `get_actionable() -> List[BulletinEntry]` - returns entries for the planner to act on.
- `find_open(topic=None, entry_type=None, goal_id=None) -> List[BulletinEntry]` - looks up open entries.
- `get_for_goal(goal_id) -> List[BulletinEntry]` - returns entries linked to a goal.
- `prune_stale(now=None) -> int` - closes stale entries.
- `compact() -> None` - rewrites the JSONL down to the latest state.
- `stats() -> Dict[str, Any]` - bulletin store statistics.

## ReminderStore (`agent_core/reminders/reminder_store.py`)
- `add(reminder) -> Reminder` - adds a reminder.
- `get(reminder_id) -> Optional[Reminder]` - fetches a reminder by ID.
- `get_due(now=None) -> List[Reminder]` - returns reminders ready to fire.
- `get_pending() -> List[Reminder]` - returns pending/snoozed reminders.
- `get_all() -> List[Reminder]` - returns all reminders.
- `update(reminder) -> None` - updates a reminder and appends it to the JSONL.
- `dismiss(reminder_id) -> Optional[Reminder]` - marks a reminder as dismissed.
- `snooze(reminder_id, minutes=15) -> Optional[Reminder]` - postpones a reminder.
- `mark_triggered(reminder) -> None` - marks a reminder as triggered (and creates the next one for recurrence).
- `count() -> Dict[str, int]` - reminder statistics.

## TodoStore (`agent_core/reminders/reminder_store.py`)
- `add(todo) -> Todo` - adds a TODO.
- `get(todo_id) -> Optional[Todo]` - fetches a TODO by ID.
- `get_pending() -> List[Todo]` - returns pending TODOs.
- `get_all() -> List[Todo]` - returns all TODOs.
- `complete(todo_id) -> Optional[Todo]` - marks a TODO as done.
- `cancel(todo_id) -> Optional[Todo]` - marks a TODO as cancelled.
- `get_overdue(now=None) -> List[Todo]` - returns overdue TODOs.
- `count() -> Dict[str, int]` - TODO statistics.

## FetchRegistry (`agent_core/web_source/fetch_registry.py`)
- `is_fetched(url) -> bool` - checks whether the URL has already been fetched.
- `is_topic_fetched(topic) -> bool` - checks whether the topic has already been fetched.
- `register(url, title, source_type, output_file, char_count, topic=None) -> None` - records a successful fetch.
- `get_stats() -> Dict[str, Any]` - fetch registry statistics.
- `get_all() -> Dict[str, Dict]` - returns all records (keyed by URL).

## TraceStore (`agent_core/tracing/trace_store.py`)
- `path -> Path` - property holding the path to the trace store file.
- `record(trace) -> None` - appends a trace to the JSONL.
- `get_recent(limit=20) -> List[Dict[str, Any]]` - returns the most recent traces.
- `get_by_episode_id(episode_id) -> Optional[Dict[str, Any]]` - fetches a trace by episode ID.
- `get_by_goal_id(goal_id, limit=10) -> List[Dict[str, Any]]` - fetches traces linked to a goal ID.
- `get_failed(limit=10) -> List[Dict[str, Any]]` - returns the most recent failed traces.
- `get_stats(limit=100) -> Dict[str, Any]` - aggregates trace statistics.

## CreativeStore (`agent_core/creative/creative_store.py`)
- `save_journal_entry(entry) -> None` - saves a creative journal entry.
- `load_journal() -> List[Dict]` - loads journal entries.
- `save_meta_goal(mg) -> None` - saves a meta-goal.
- `load_meta_goals() -> List[Dict]` - loads meta-goals.
- `get_recent_meta_goals(hours=24.0) -> List[Dict]` - returns recent meta-goals (proposed/accepted).
- `save_conversation_memory(entry) -> None` - saves a memory entry.
- `load_conversation_memories() -> List[Dict]` - loads conversation memories.
- `get_memories_by_type(memory_type) -> List[Dict]` - filters memories by type.
- `get_memories_by_importance(min_importance=0.5) -> List[Dict]` - filters memories by importance.
- `save_workspace_session(session) -> None` - saves a workspace session summary.
- `load_workspace_sessions() -> List[Dict]` - loads workspace sessions.
- `log_event(event_name, payload=None) -> None` - records a telemetry event.
- `load_events(last_n=50) -> List[Dict]` - loads the most recent events.
- `record_tensions(categories) -> None` - records the detected tension categories.
- `get_tension_streak(category) -> int` - returns the tension streak for a category.
- `save_personality_signal(signal) -> None` - saves a personality signal.
- `load_personality_signals() -> List[Dict]` - loads personality signals.

## VectorStore (`agent_core/semantic/vector_store.py`)
- `load() -> int` - loads vectors from the JSONL.
- `save() -> int` - appends dirty entries.
- `save_full() -> int` - rewrites the whole store to the JSONL.
- `list_ids_by_namespace(namespace) -> List[str]` - returns the IDs for a namespace.
- `add(entry_id, text, vector, metadata=None) -> bool` - adds/updates a vector entry.
- `add_text(entry_id, text, embedding_model, metadata=None) -> bool` - embed + add.
- `add_texts_batch(entries, embedding_model) -> int` - batch embed + add.
- `remove(entry_id) -> bool` - removes an entry.
- `get(entry_id) -> Optional[VectorEntry]` - fetches an entry.
- `search(query_vector, top_k=10, threshold=0.3, namespace=None) -> List[SearchResult]` - similarity search.
- `search_text(query, embedding_model, top_k=10, threshold=0.3, namespace=None) -> List[SearchResult]` - embed query + search.
- `count() -> int` - number of entries in the store.
- `get_by_namespace(namespace) -> List[VectorEntry]` - entries from a namespace.
- `stats() -> Dict[str, Any]` - vector store statistics.
