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

const getHeaders = (token, supabaseToken, extraHeaders = {}) => {
  const headers = { ...extraHeaders };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  if (supabaseToken) {
    headers['X-Supabase-Token'] = supabaseToken;
  }
  return headers;
};

export const mcpService = {
  async getConnections(token, supabaseToken) {
    const response = await fetch(`${API_BASE_URL}/mcp/connections`, {
      headers: getHeaders(token, supabaseToken),
    });
    if (!response.ok) {
      throw new Error(await readErrorMessage(response, 'Failed to fetch MCP connections'));
    }
    return response.json();
  },

  async connectJira(email, domain, apiToken, token, supabaseToken) {
    const response = await fetch(`${API_BASE_URL}/mcp/jira/connect`, {
      method: 'POST',
      headers: getHeaders(token, supabaseToken, { 'Content-Type': 'application/json' }),
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

  async connectSlack(slackToken, token, supabaseToken) {
    const response = await fetch(`${API_BASE_URL}/mcp/slack/connect`, {
      method: 'POST',
      headers: getHeaders(token, supabaseToken, { 'Content-Type': 'application/json' }),
      body: JSON.stringify({ slack_token: slackToken }),
    });

    if (!response.ok) {
      throw new Error(await readErrorMessage(response, 'Invalid Slack token'));
    }
    return response.json();
  },

  async connectSalesforce(accessToken, instanceUrl, token, supabaseToken) {
    const response = await fetch(`${API_BASE_URL}/mcp/salesforce/connect`, {
      method: 'POST',
      headers: getHeaders(token, supabaseToken, { 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        access_token: accessToken,
        instance_url: instanceUrl,
      }),
    });

    if (!response.ok) {
      throw new Error(await readErrorMessage(response, 'Invalid Salesforce credentials'));
    }
    return response.json();
  },

  async disconnectProvider(provider, token, supabaseToken) {
    const response = await fetch(`${API_BASE_URL}/mcp/disconnect/${encodeURIComponent(provider)}`, {
      method: 'DELETE',
      headers: getHeaders(token, supabaseToken),
    });

    if (!response.ok) {
      throw new Error(await readErrorMessage(response, `Failed to disconnect ${provider}`));
    }
    return response.json();
  },

  async connectProvider(provider, providerUserId, token, supabaseToken) {
    const response = await fetch(`${API_BASE_URL}/mcp/connections`, {
      method: 'POST',
      headers: getHeaders(token, supabaseToken, { 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        provider,
        provider_user_id: providerUserId,
        connected: true,
      }),
    });

    if (!response.ok) {
      throw new Error(await readErrorMessage(response, `Failed to connect ${provider}`));
    }
    return response.json();
  },

  async connectCustomMcp(url, customToken, token, supabaseToken) {
    const response = await fetch(`${API_BASE_URL}/mcp/custom/connect`, {
      method: 'POST',
      headers: getHeaders(token, supabaseToken, { 'Content-Type': 'application/json' }),
      body: JSON.stringify({ url, token: customToken }),
    });
    if (!response.ok) {
      throw new Error(await readErrorMessage(response, 'Failed to connect Custom MCP Server'));
    }
    return response.json();
  },

  async connectNotion(email, notionToken, token, supabaseToken) {
    const response = await fetch(`${API_BASE_URL}/mcp/notion/connect`, {
      method: 'POST',
      headers: getHeaders(token, supabaseToken, { 'Content-Type': 'application/json' }),
      body: JSON.stringify({ email, token: notionToken }),
    });
    if (!response.ok) {
      throw new Error(await readErrorMessage(response, 'Failed to connect Notion'));
    }
    return response.json();
  },

  async connectGmail(email, gmailToken, token, supabaseToken) {
    const response = await fetch(`${API_BASE_URL}/mcp/gmail/connect`, {
      method: 'POST',
      headers: getHeaders(token, supabaseToken, { 'Content-Type': 'application/json' }),
      body: JSON.stringify({ email, token: gmailToken }),
    });
    if (!response.ok) {
      throw new Error(await readErrorMessage(response, 'Failed to connect Gmail'));
    }
    return response.json();
  },

  async listTools(token, supabaseToken) {
    const response = await fetch(`${API_BASE_URL}/mcp/tools`, {
      headers: getHeaders(token, supabaseToken),
    });
    if (!response.ok) {
      throw new Error(await readErrorMessage(response, 'Failed to fetch registered tools'));
    }
    return response.json();
  },

  async createOAuthContext(token, supabaseToken) {
    const response = await fetch(`${API_BASE_URL}/mcp/oauth/context`, {
      method: 'POST',
      headers: getHeaders(token, supabaseToken),
    });

    if (!response.ok) {
      throw new Error(await readErrorMessage(response, 'Failed to prepare OAuth login context'));
    }

    return response.json();
  },

  getGithubLoginUrl(stateToken) {
    const params = new URLSearchParams();
    if (stateToken) {
      params.set('state_token', stateToken);
    }
    const query = params.toString();
    return `${API_BASE_URL}/mcp/github/login${query ? `?${query}` : ''}`;
  },

  getOAuthLoginUrl(provider, stateToken) {
    const params = new URLSearchParams();
    if (stateToken) {
      params.set('state_token', stateToken);
    }
    const query = params.toString();
    return `${API_BASE_URL}/mcp/${encodeURIComponent(provider)}/login${query ? `?${query}` : ''}`;
  }
};
