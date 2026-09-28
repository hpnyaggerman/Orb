export function mergeModelChoices(configs, availableModels) {
  const choices = [];
  const seen = new Set();

  for (const config of Array.isArray(configs) ? configs : []) {
    const value = typeof config?.model_name === "string" ? config.model_name.trim() : "";
    if (!value || seen.has(value)) continue;
    seen.add(value);
    choices.push({ value, id: config.id, type: "model" });
  }

  for (const raw of Array.isArray(availableModels) ? availableModels : []) {
    const value = typeof raw === "string" ? raw.trim() : "";
    if (!value || seen.has(value)) continue;
    seen.add(value);
    choices.push({ value, type: "available" });
  }

  return choices;
}

// A profile saved before profiles had names is labelled by its model and server;
// "(agent)" tells apart the Agent-lane copy the old editor kept for each server,
// and sits before the server so a label cut short in a narrow list keeps it.
export function profileLabel(profile) {
  const name = typeof profile?.name === "string" ? profile.name.trim() : "";
  if (name) return name;
  const model = profile?.model_name || "default";
  const agent = profile?.role === "agent" ? " (agent)" : "";
  return `${model}${agent} @ ${hostOf(profile?.endpoint_url || "")}`;
}

function hostOf(url) {
  try {
    return new URL(url).host || url;
  } catch {
    return url;
  }
}

export function filterModelChoices(choices, query) {
  const needle = normalizeSearchValue(query).trim();
  if (!needle) return choices;
  const compactNeedle = compactSearchValue(needle);
  return choices.filter((item) => {
    const haystack = normalizeSearchValue(item.value);
    return haystack.includes(needle) || (compactNeedle && compactSearchValue(haystack).includes(compactNeedle));
  });
}

function normalizeSearchValue(value) {
  return String(value ?? "")
    .normalize("NFKC")
    .toLowerCase();
}

function compactSearchValue(value) {
  return value.replace(/[^\p{L}\p{N}]+/gu, "");
}
