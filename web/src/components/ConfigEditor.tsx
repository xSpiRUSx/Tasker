import { Plus, RefreshCw, Save, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { getRouterConfig, saveRouterConfig } from "../api/client";
import type { ConfigRecord, RouterConfigDocument } from "../api/types";

type Section = "projects" | "workflows" | "tools";

interface ConfigEditorProps {
  setError: (value: string | null) => void;
  setToast: (value: string | null) => void;
}

const SECTIONS: Array<{ id: Section; label: string }> = [
  { id: "projects", label: "Проекты" },
  { id: "workflows", label: "Workflow" },
  { id: "tools", label: "Инструменты" },
];

export function ConfigEditor({ setError, setToast }: ConfigEditorProps) {
  const [doc, setDoc] = useState<RouterConfigDocument | null>(null);
  const [section, setSection] = useState<Section>("projects");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draftJson, setDraftJson] = useState("");
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState<"load" | "save" | null>(null);

  const load = useCallback(async () => {
    setBusy("load");
    try {
      const config = await getRouterConfig();
      setDoc(config);
      setDirty(false);
      setError(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Не удалось загрузить конфигурацию");
    } finally {
      setBusy(null);
    }
  }, [setError]);

  useEffect(() => {
    void load();
  }, [load]);

  const items = useMemo(() => (doc ? doc[section] : []), [doc, section]);
  const selected = useMemo(
    () => items.find((item) => itemId(item) === selectedId) || null,
    [items, selectedId],
  );

  useEffect(() => {
    if (!doc) return;
    const exists = doc[section].some((item) => itemId(item) === selectedId);
    if (!exists) {
      setSelectedId(itemId(doc[section][0]) || null);
    }
  }, [doc, section, selectedId]);

  useEffect(() => {
    setDraftJson(selected ? JSON.stringify(selected, null, 2) : "");
  }, [selected]);

  function updateSelected(patch: ConfigRecord) {
    if (!selectedId) return;
    setDoc((current) => {
      if (!current) return current;
      return {
        ...current,
        [section]: current[section].map((item) => (itemId(item) === selectedId ? { ...item, ...patch } : item)),
      };
    });
    setDirty(true);
  }

  function replaceSelected(nextItem: ConfigRecord) {
    const nextId = itemId(nextItem);
    if (!nextId || !selectedId) {
      setError("У объекта должен быть непустой id");
      return;
    }
    setDoc((current) => {
      if (!current) return current;
      return {
        ...current,
        [section]: current[section].map((item) => (itemId(item) === selectedId ? nextItem : item)),
      };
    });
    setSelectedId(nextId);
    setDirty(true);
    setError(null);
  }

  function addItem() {
    if (!doc) return;
    const nextItem = createDefaultItem(section, doc);
    setDoc({ ...doc, [section]: [...doc[section], nextItem] });
    setSelectedId(itemId(nextItem));
    setDirty(true);
  }

  function removeItem() {
    if (!doc || !selected) return;
    const id = itemId(selected);
    if (!window.confirm(`Удалить ${id}?`)) return;
    setDoc({ ...doc, [section]: doc[section].filter((item) => itemId(item) !== id) });
    setDirty(true);
  }

  async function save() {
    if (!doc) return;
    setBusy("save");
    try {
      const saved = await saveRouterConfig(doc);
      setDoc(saved);
      setDirty(false);
      setToast("Конфигурация сохранена");
      setError(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Не удалось сохранить конфигурацию");
    } finally {
      setBusy(null);
    }
  }

  function applyJson() {
    try {
      const parsed = JSON.parse(draftJson) as unknown;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        setError("JSON объекта должен быть словарем");
        return;
      }
      replaceSelected(parsed as ConfigRecord);
    } catch (error) {
      setError(error instanceof Error ? error.message : "JSON не разобран");
    }
  }

  return (
    <main className="main settings-main">
      <section className="task-header">
        <div>
          <div className="task-header__title">
            <h1>Конфигурация</h1>
            {dirty ? <span className="status-badge status-badge--changes">есть изменения</span> : null}
          </div>
          <dl className="task-header__meta">
            <dt>projects.yml</dt>
            <dd>{doc?.projects_path || "..."}</dd>
            <dt>workflows.yml</dt>
            <dd>{doc?.workflows_path || "..."}</dd>
          </dl>
        </div>
        <div className="task-header__actions">
          <button className="icon-button" type="button" disabled={busy !== null} onClick={() => void load()} title="Обновить">
            <RefreshCw size={16} />
          </button>
          <button type="button" disabled={!dirty || busy !== null} onClick={() => void save()}>
            <Save size={16} />
            {busy === "save" ? "Сохраняю..." : "Сохранить"}
          </button>
        </div>
      </section>

      <section className="config-layout">
        <aside className="panel config-sidebar">
          <div className="tabs config-tabs">
            {SECTIONS.map((item) => (
              <button
                className={section === item.id ? "tab tab--active" : "tab"}
                key={item.id}
                type="button"
                onClick={() => setSection(item.id)}
              >
                {item.label}
              </button>
            ))}
          </div>
          <div className="section-title">
            <h2>{SECTIONS.find((item) => item.id === section)?.label}</h2>
            <button className="icon-button" type="button" onClick={addItem} disabled={!doc}>
              <Plus size={16} />
            </button>
          </div>
          <div className="config-list">
            {items.map((item) => (
              <button
                className={itemId(item) === selectedId ? "config-list-item config-list-item--selected" : "config-list-item"}
                key={itemId(item)}
                type="button"
                onClick={() => setSelectedId(itemId(item))}
              >
                <strong>{String(item.name || item.id || "без имени")}</strong>
                <span>{itemId(item)}</span>
              </button>
            ))}
            {!items.length ? <div className="empty">Пока пусто.</div> : null}
          </div>
        </aside>

        <section className="panel config-editor">
          {selected ? (
            <>
              <div className="section-title">
                <h2>{String(selected.name || selected.id)}</h2>
                <button className="icon-button" type="button" onClick={removeItem}>
                  <Trash2 size={16} />
                </button>
              </div>
              {section === "projects" ? <ProjectFields item={selected} update={updateSelected} setSelectedId={setSelectedId} /> : null}
              {section === "workflows" ? <WorkflowFields item={selected} update={updateSelected} setSelectedId={setSelectedId} /> : null}
              {section === "tools" ? <ToolFields item={selected} update={updateSelected} setSelectedId={setSelectedId} /> : null}
              <div className="config-json">
                <label>
                  <span>JSON объекта</span>
                  <textarea value={draftJson} onChange={(event) => setDraftJson(event.target.value)} rows={12} />
                </label>
                <button type="button" onClick={applyJson}>
                  Применить JSON
                </button>
              </div>
            </>
          ) : (
            <div className="empty">Выберите объект.</div>
          )}
        </section>
      </section>
    </main>
  );
}

function ProjectFields({
  item,
  update,
  setSelectedId,
}: {
  item: ConfigRecord;
  update: (patch: ConfigRecord) => void;
  setSelectedId: (id: string) => void;
}) {
  return (
    <div className="config-form">
      <TextField label="ID" value={stringValue(item.id)} onChange={(value) => { update({ id: value }); setSelectedId(value); }} />
      <TextField label="Название" value={stringValue(item.name)} onChange={(value) => update({ name: value })} />
      <TextField label="Путь" value={stringValue(item.path)} onChange={(value) => update({ path: value || null })} />
      <TextareaField label="Описание" value={stringValue(item.description)} onChange={(value) => update({ description: value })} rows={3} />
      <ListField label="Алиасы" value={arrayValue(item.aliases)} onChange={(value) => update({ aliases: value })} />
      <ListField label="Инструменты" value={arrayValue(item.tools)} onChange={(value) => update({ tools: value })} />
      <TextField label="Тип проекта" value={stringValue(item.project_type)} onChange={(value) => update({ project_type: value || undefined })} />
      <TextField label="Профиль проверки" value={stringValue(item.validation_profile)} onChange={(value) => update({ validation_profile: value || undefined })} />
      <ListField label="Команды проверки" value={arrayValue(item.test_commands)} onChange={(value) => update({ test_commands: value })} />
      <ListField label="Запрещенные пути" value={arrayValue(item.blocked_paths)} onChange={(value) => update({ blocked_paths: value })} />
      <ListField label="Разрешенные пути" value={arrayValue(item.allowed_paths)} onChange={(value) => update({ allowed_paths: value })} />
    </div>
  );
}

function WorkflowFields({
  item,
  update,
  setSelectedId,
}: {
  item: ConfigRecord;
  update: (patch: ConfigRecord) => void;
  setSelectedId: (id: string) => void;
}) {
  return (
    <div className="config-form">
      <TextField label="ID" value={stringValue(item.id)} onChange={(value) => { update({ id: value }); setSelectedId(value); }} />
      <TextField label="Название" value={stringValue(item.name)} onChange={(value) => update({ name: value })} />
      <TextareaField label="Описание" value={stringValue(item.description)} onChange={(value) => update({ description: value })} rows={3} />
      <ListField label="Проекты" value={arrayValue(item.project_ids)} onChange={(value) => update({ project_ids: value })} />
      <ListField label="Интенты" value={arrayValue(item.intents)} onChange={(value) => update({ intents: value })} />
      <ListField label="Типы задач" value={arrayValue(item.task_kinds)} onChange={(value) => update({ task_kinds: value })} />
      <ListField label="Сложность" value={arrayValue(item.complexity)} onChange={(value) => update({ complexity: value })} />
      <ListField label="Инструменты" value={arrayValue(item.required_tools)} onChange={(value) => update({ required_tools: value })} />
      <ListField label="Approval gates" value={arrayValue(item.approval_gates)} onChange={(value) => update({ approval_gates: value })} />
      <ListField label="Risk flags" value={arrayValue(item.risk_flags)} onChange={(value) => update({ risk_flags: value })} />
      <ListField label="Шаги" value={arrayValue(item.steps)} onChange={(value) => update({ steps: value })} />
      <div className="config-booleans">
        <BooleanField label="Требует ТЗ" value={booleanValue(item.requires_spec)} onChange={(value) => update({ requires_spec: value })} />
        <BooleanField label="Требует тесты" value={booleanValue(item.requires_tests)} onChange={(value) => update({ requires_tests: value })} />
        <BooleanField label="Требует ревью" value={booleanValue(item.requires_review)} onChange={(value) => update({ requires_review: value })} />
        <BooleanField label="Config approval" value={booleanValue(item.requires_config_approval)} onChange={(value) => update({ requires_config_approval: value })} />
        <BooleanField label="Deploy prep" value={booleanValue(item.requires_deploy_prep)} onChange={(value) => update({ requires_deploy_prep: value })} />
      </div>
    </div>
  );
}

function ToolFields({
  item,
  update,
  setSelectedId,
}: {
  item: ConfigRecord;
  update: (patch: ConfigRecord) => void;
  setSelectedId: (id: string) => void;
}) {
  return (
    <div className="config-form">
      <TextField label="ID" value={stringValue(item.id)} onChange={(value) => { update({ id: value }); setSelectedId(value); }} />
      <TextField label="Название" value={stringValue(item.name)} onChange={(value) => update({ name: value })} />
      <TextField label="Тип" value={stringValue(item.type)} onChange={(value) => update({ type: value })} />
      <TextareaField label="Описание" value={stringValue(item.description)} onChange={(value) => update({ description: value })} rows={4} />
    </div>
  );
}

function TextField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label>
      <span>{label}</span>
      <input value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function TextareaField({
  label,
  value,
  onChange,
  rows = 4,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
}) {
  return (
    <label>
      <span>{label}</span>
      <textarea value={value} onChange={(event) => onChange(event.target.value)} rows={rows} />
    </label>
  );
}

function ListField({ label, value, onChange }: { label: string; value: string[]; onChange: (value: string[]) => void }) {
  return (
    <label>
      <span>{label}</span>
      <textarea value={value.join("\n")} onChange={(event) => onChange(splitList(event.target.value))} rows={3} />
    </label>
  );
}

function BooleanField({ label, value, onChange }: { label: string; value: boolean; onChange: (value: boolean) => void }) {
  return (
    <label className="toggle">
      <input checked={value} onChange={(event) => onChange(event.target.checked)} type="checkbox" />
      {label}
    </label>
  );
}

function createDefaultItem(section: Section, doc: RouterConfigDocument): ConfigRecord {
  const id = uniqueId(section === "projects" ? "new_project" : section === "workflows" ? "new_workflow" : "new_tool", doc[section]);
  if (section === "projects") {
    return {
      id,
      name: "Новый проект",
      path: ".",
      aliases: [],
      description: "Описание проекта",
      tools: defaultTools(doc),
    };
  }
  if (section === "workflows") {
    return {
      id,
      name: "Новый workflow",
      description: "Описание workflow",
      project_ids: ["*"],
      intents: ["code_change"],
      task_kinds: ["feature"],
      complexity: ["simple"],
      required_tools: defaultTools(doc),
      requires_spec: false,
      requires_tests: true,
      requires_review: true,
      requires_config_approval: false,
      requires_deploy_prep: false,
      approval_gates: ["plan", "diff", "commit"],
      steps: ["Собрать контекст.", "Выполнить изменение.", "Проверить результат."],
    };
  }
  return { id, name: "Новый инструмент", type: "coding_agent", description: "Описание инструмента" };
}

function defaultTools(doc: RouterConfigDocument): string[] {
  const codex = doc.tools.find((tool) => itemId(tool) === "codex");
  return codex ? ["codex"] : doc.tools[0] ? [itemId(doc.tools[0])] : [];
}

function uniqueId(base: string, items: ConfigRecord[]): string {
  const existing = new Set(items.map(itemId));
  if (!existing.has(base)) return base;
  let index = 2;
  while (existing.has(`${base}_${index}`)) {
    index += 1;
  }
  return `${base}_${index}`;
}

function itemId(item?: ConfigRecord | null): string {
  return item?.id ? String(item.id) : "";
}

function stringValue(value: unknown): string {
  return value === null || value === undefined ? "" : String(value);
}

function booleanValue(value: unknown): boolean {
  return value === true;
}

function arrayValue(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)) : [];
}

function splitList(value: string): string[] {
  return value
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}
