import { useEffect, useState } from "react";

import { supabase } from "./lib/supabase";

import Login from "./components/Login";
import Dashboard from "./components/Dashboard";

function App() {

  const [session, setSession] = useState(undefined);

  useEffect(() => {

    const fetchSession = async () => {

      const { data, error } = await supabase.auth.getSession();

      if (error) {
        console.error(error);
      }

      setSession(data.session);
    };

    fetchSession();

    const {
      data: authListener,
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session);
    });

    return () => {
      authListener.subscription.unsubscribe();
    };

  }, []);

  if (session === undefined) {
    return <div>Loading...</div>;
  }

  return (
    <>
      {session ? <Dashboard /> : <Login />}
    </>
  );
}

export default App;