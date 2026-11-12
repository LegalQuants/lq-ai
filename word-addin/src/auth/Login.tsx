import {
  Alert,
  Button,
  Card,
  Flex,
  Group,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useAuth } from "@/auth/AuthContext";
import { useState } from "react";

export default function TaskPaneLogin() {
  const auth = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [alert, setAlert] = useState<string | null>(null);

  const handleLogin = async () => {
    try {
      const normalized = username.trim();
      await auth.login(normalized, password, "taskpane");
      setAlert(null);
    } catch (err: any) {
      setAlert(err?.message ?? "Unable to login");
    }
  };

  return (
    <Flex direction="column" h="100%">
      <Group justify="center" align="flex-start" style={{ flex: 1 }}>
        <Card style={{ margin: "50px 4px" }}>
          <Stack>
            <Title order={2} children="Login" />

            <TextInput
              value={username}
              label="Email Address"
              onChange={(e) => setUsername(e.currentTarget.value)}
            />
            <PasswordInput
              label="Password"
              value={password}
              onChange={(e) => setPassword(e.currentTarget.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  handleLogin();
                }
              }}
            />
            {alert && (
              <Alert color="red">
                <Text fw={700} c="red">
                  {alert}
                </Text>
              </Alert>
            )}

            <Button
              onClick={(e) => {
                e.preventDefault();
                handleLogin();
              }}
              children="Login"
            />
          </Stack>
        </Card>
      </Group>
    </Flex>
  );
}
