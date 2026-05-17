const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export const mcpService = {
  async getConnections(token) {
    const headers = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    const response = await fetch(`${API_BASE_URL}/mcp/connections`, { headers });
    if (!response.ok) {
      throw new Error('Failed to fetch connections');
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
      throw new Error('Invalid Jira credentials or domain');
    }
    return response.json();
  },

  getGithubLoginUrl(userKey) {
    const key = userKey || 'demo';
    return `${API_BASE_URL}/mcp/github/login?user_key=${encodeURIComponent(key)}`;
  }
};
