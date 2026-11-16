export function studioAskUrl(projectId: string, prompt: string): string { return `/app/projects/${projectId}?ask=${encodeURIComponent(prompt)}`; }
