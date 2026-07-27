"""Propagowanie tagów wybranych w Settings na synchronizowane obiekty."""


def tag_synced_objects(objects, configured_tags):
    """Dodaj tagi z Settings do nowych i aktualizowanych obiektów obsługujących tags."""
    tags = list(configured_tags)
    if not tags:
        return 0

    tagged = 0
    seen = set()
    for obj in objects:
        # Ten sam obiekt może wystąpić na listach created oraz synced. Stabilny
        # klucz model+PK zapobiega powtarzaniu operacji M2M.
        meta = getattr(obj, "_meta", None)
        identity = (
            getattr(meta, "label_lower", type(obj).__name__),
            getattr(obj, "pk", id(obj)),
        )
        if identity in seen:
            continue
        seen.add(identity)

        tag_manager = getattr(obj, "tags", None)
        if tag_manager is not None and callable(getattr(tag_manager, "add", None)):
            # add() zachowuje dotychczasowe tagi i ignoruje relacje już istniejące.
            tag_manager.add(*tags)
            tagged += 1
    return tagged
