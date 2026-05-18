const API_BASE_URL = import.meta.env.DEV
  ? '/api'
  : import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

const readErrorMessage = async (response, fallbackMessage) => {
  try {
    const raw = await response.text();
    if (!raw) return fallbackMessage;

    try {
      const parsed = JSON.parse(raw);
      if (typeof parsed.detail === 'string') return parsed.detail;
      if (typeof parsed.detail?.message === 'string') return parsed.detail.message;
      if (typeof parsed.message === 'string') return parsed.message;
    } catch {
      return raw;
    }

    return fallbackMessage;
  } catch {
    return fallbackMessage;
  }
};

export const mcpService = {
  async getConnections(token) {
    const headers = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    const response = await fetch(`${API_BASE_URL}/mcp/connections`, { headers });
    if (!response.ok) {
      throw new Error(await readErrorMessage(response, 'Failed to fetch MCP connections'));
    }
    return response.json();
  },

  async connectJira(email, domain, apiToken, token) {
    const headers = {
      'Content-Type': 'application/json',
    };
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    const response = await fetch(`${API_BASE_URL}/mcp/jira/connect`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        jira_email: email,
        jira_domain: domain,
        jira_api_token: apiToken,
      }),
    });

    if (!response.ok) {
      throw new Error(await readErrorMessage(response, 'Invalid Jira credentials or domain'));
    }
    return response.json();
  },

  getGithubLoginUrl(userKey) {
    const key = userKey || 'demo';
    return `${API_BASE_URL}/mcp/github/login?user_key=${encodeURIComponent(key)}`;
  }
};
