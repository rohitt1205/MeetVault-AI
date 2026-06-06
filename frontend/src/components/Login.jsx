import { supabase } from "../lib/supabase";

function Login() {

  const handleMicrosoftLogin = async () => {
    await supabase.auth.signInWithOAuth({
      provider: "azure",
      options: {
        redirectTo: window.location.origin,
        scopes:
          "openid profile email offline_access User.Read Calendars.Read Files.Read OnlineMeetings.Read OnlineMeetingTranscript.Read.All"
      }
    });
  };

  return (
    <div>
      <h1>MeetVault.AI</h1>

      <button onClick={handleMicrosoftLogin}>
        Continue with Microsoft
      </button>
    </div>
  );
}

export default Login;
