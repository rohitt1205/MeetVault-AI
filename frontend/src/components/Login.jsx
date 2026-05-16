import { supabase } from "../lib/supabase";

function Login() {

  const handleMicrosoftLogin = async () => {

    await supabase.auth.signInWithOAuth({
      provider: "azure",
      options: {
        scopes: "openid profile email User.Read"
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