"use client";

import {
  Check,
  Clipboard,
  LoaderCircle,
  Pencil,
  Save,
  Undo2,
} from "lucide-react";
import { useState } from "react";

import { setupClient } from "@/lib/setup-persistence";

export type EnvironmentVariableRow = {
  id: string;
  name: string;
  value: string;
  sensitive: boolean;
  configured: boolean;
};

export function EnvironmentVariableTable({
  variables,
  updatedAt,
  canEdit,
}: {
  variables: EnvironmentVariableRow[];
  updatedAt: string | null;
  canEdit: boolean;
}) {
  const [savedVariables, setSavedVariables] = useState(() => cloneVariables(variables));
  const [draftVariables, setDraftVariables] = useState(() => cloneVariables(variables));
  const [lastUpdatedAt, setLastUpdatedAt] = useState(updatedAt);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  function startEditing() {
    setDraftVariables(cloneVariables(savedVariables));
    setMessage(null);
    setEditing(true);
  }

  function discardChanges() {
    setDraftVariables(cloneVariables(savedVariables));
    setMessage(null);
    setEditing(false);
  }

  function updateVariable(
    index: number,
    key: "name" | "value",
    value: string,
  ) {
    setDraftVariables((current) =>
      current.map((variable, itemIndex) =>
        itemIndex === index ? { ...variable, [key]: value } : variable,
      ),
    );
  }

  async function submitChanges() {
    if (saving) {
      return;
    }
    const validationError = validateVariables(draftVariables);
    if (validationError) {
      setMessage(validationError);
      return;
    }

    setSaving(true);
    setMessage(null);
    try {
      const result = await setupClient().setup.saveEnvironmentVariables.mutate({
        variables: draftVariables.map((variable) => ({
          id: variable.id || null,
          name: variable.name,
          value: variable.value,
          sensitive: variable.sensitive,
          retainExisting:
            variable.sensitive && variable.configured && variable.value === "",
        })),
      });
      const nextVariables = cloneVariables(result.variables);
      setSavedVariables(nextVariables);
      setDraftVariables(cloneVariables(nextVariables));
      setLastUpdatedAt(result.updatedAt);
      setEditing(false);
      setMessage("Environment variables saved");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function copyValue(index: number, value: string) {
    await navigator.clipboard.writeText(value);
    setCopiedIndex(index);
    window.setTimeout(() => setCopiedIndex(null), 1400);
  }

  return (
    <>
      <div className="environmentSectionHeader">
        <div>
          <h2 id="environment-table-title">Saved configuration</h2>
          <p>Organization values are stored in Postgres; secrets are encrypted by OpenBao.</p>
        </div>
        <div className="environmentSectionControls">
          <span>
            {lastUpdatedAt
              ? `Updated ${new Date(lastUpdatedAt).toLocaleString()}`
              : "No saved configuration"}
          </span>
          {editing ? (
            <EnvironmentEditActions
              saving={saving}
              onDiscard={discardChanges}
              onSubmit={submitChanges}
            />
          ) : (
            <button
              className="secondaryButton"
              type="button"
              disabled={!canEdit}
              title={canEdit ? "Edit environment variables" : "Write role required"}
              onClick={startEditing}
            >
              <Pencil size={16} />
              Edit
            </button>
          )}
        </div>
      </div>

      {message ? (
        <div className={`environmentMessage ${editing ? "error" : "ok"}`} role="status">
          {message}
        </div>
      ) : null}

      <div className="environmentTableWrap">
        <table className="environmentTable">
          <thead>
            <tr>
              <th scope="col">Environment variable</th>
              <th scope="col">Value</th>
            </tr>
          </thead>
          <tbody>
            {draftVariables.map((variable, index) => {
              const configured = variable.sensitive
                ? variable.configured
                : Boolean(variable.value);
              return (
                <tr key={variable.id || variable.name}>
                  <th scope="row">
                    {editing ? (
                      <input
                        aria-label={`Environment variable name ${index + 1}`}
                        className="environmentInput environmentNameInput"
                        value={variable.name}
                        onChange={(event) =>
                          updateVariable(index, "name", event.target.value)
                        }
                      />
                    ) : (
                      <code>{variable.name}</code>
                    )}
                  </th>
                  <td>
                    <div className="environmentValue">
                      {editing ? (
                        <input
                          aria-label={`${variable.name || "Environment variable"} value`}
                          className="environmentInput environmentValueInput"
                          type={variable.sensitive ? "password" : "text"}
                          value={variable.value}
                          placeholder={
                            variable.sensitive && variable.configured
                              ? "Configured; enter a new value to replace"
                              : undefined
                          }
                          onChange={(event) =>
                            updateVariable(index, "value", event.target.value)
                          }
                        />
                      ) : (
                        <code className={!configured ? "empty" : ""}>
                          {configured
                            ? variable.sensitive
                              ? "Configured in OpenBao"
                              : variable.value
                            : "Not configured"}
                        </code>
                      )}
                      <div className="environmentValueActions">
                        {!editing && configured && !variable.sensitive ? (
                          <button
                            className="iconButton"
                            type="button"
                            aria-label={`Copy ${variable.name}`}
                            onClick={() => copyValue(index, variable.value)}
                          >
                            {copiedIndex === index ? (
                              <Check size={15} />
                            ) : (
                              <Clipboard size={15} />
                            )}
                          </button>
                        ) : null}
                      </div>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {editing ? (
        <div className="environmentBottomActions">
          <EnvironmentEditActions
            saving={saving}
            onDiscard={discardChanges}
            onSubmit={submitChanges}
          />
        </div>
      ) : null}
    </>
  );
}

function EnvironmentEditActions({
  saving,
  onDiscard,
  onSubmit,
}: {
  saving: boolean;
  onDiscard: () => void;
  onSubmit: () => void;
}) {
  return (
    <div className="environmentEditActions">
      <button
        className="secondaryButton"
        type="button"
        disabled={saving}
        onClick={onDiscard}
      >
        <Undo2 size={16} />
        Discard
      </button>
      <button
        className="secondaryButton primaryAction"
        type="button"
        disabled={saving}
        aria-busy={saving}
        onClick={onSubmit}
      >
        {saving ? (
          <LoaderCircle className="loadingSpinner" size={16} />
        ) : (
          <Save size={16} />
        )}
        {saving ? "Submitting" : "Submit"}
      </button>
    </div>
  );
}

function cloneVariables(variables: EnvironmentVariableRow[]): EnvironmentVariableRow[] {
  return variables.map((variable) => ({ ...variable }));
}

function validateVariables(variables: EnvironmentVariableRow[]): string | null {
  const names = variables.map((variable) => variable.name.trim());
  if (names.some((name) => !/^[A-Za-z_][A-Za-z0-9_]*$/.test(name))) {
    return "Variable names must start with a letter or underscore and contain only letters, numbers, and underscores";
  }
  if (new Set(names).size !== names.length) {
    return "Environment variable names must be unique";
  }
  return null;
}
