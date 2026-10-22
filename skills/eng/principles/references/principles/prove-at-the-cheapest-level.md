# Prove at the Cheapest Level

Prove each fact at the cheapest level that can prove it. Give the real system (a running instance, a real device, a real network) only the facts that only the real system can show.

The levels, cheapest first: the type checker, a unit test, an integration test that runs real components in one process, a script against the real system, a person looking. A fact belongs at the cheapest level that can still fail on it. Logic, edge cases, ordering and timing belong in unit and integration tests. A fake clock proves in milliseconds what real time proves in minutes. The real system proves what crosses its boundaries: separate processes wired together, a real build, the platform's own behavior.

The same rule governs building the proof. Develop a script, a helper or a fixture at a level with fast feedback, and run the real system to accept it, not to debug it. Every real run is expensive, so plan each one.

Applies when choosing a check's tier, when writing a verification script or its helpers, and when a verification run is slow. Ask which part of it needs the real system. Move the rest down a level.
