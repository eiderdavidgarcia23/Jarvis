# Bitácora de Jarvis

- Migración del modelo de lenguaje de llama-3.3-70b-versatile a openai/gpt-oss-120b, porque Groq retiró el modelo anterior.
- Búsqueda web integrada mediante Tavily, para consultar información actual.
- Memoria persistente por usuario, para recordar conversaciones anteriores.
- Sistema de recordatorios con notificaciones en el navegador.
- Modo avanzado: comandos combinados y memoria de preferencias de estilo por usuario.
- Voz local con Piper TTS.
- Modo Jarvis en segundo plano: escucha continua activada diciendo "Jarvis", con animación del reactor mientras escucha y responde.
