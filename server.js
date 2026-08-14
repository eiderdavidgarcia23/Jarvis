const express = require('express');
const cors = require('cors');
const fs = require('fs');
const path = require('path');
require('dotenv').config();
const Groq = require('groq-sdk');

const app = express();
app.use(cors());
app.use(express.json());
app.use(express.static('public'));

const groq = new Groq({ apiKey: process.env.GROQ_API_KEY });

const MEMORY_FILE = path.join(__dirname, 'memoria.json');

function cargarMemoria() {
  if (!fs.existsSync(MEMORY_FILE)) return [];
  return JSON.parse(fs.readFileSync(MEMORY_FILE, 'utf8'));
}

function guardarMemoria(historial) {
  fs.writeFileSync(MEMORY_FILE, JSON.stringify(historial, null, 2));
}

app.post('/chat', async (req, res) => {
  try {
    const mensajeUsuario = req.body.mensaje;
    let historial = cargarMemoria();

    const mensajes = [
      { role: 'system', content: 'Eres Jarvis, el asistente personal inteligente. Eres util, directo y recuerdas todo lo que el usuario te ha contado antes.' },
      ...historial.map(h => ({ role: h.role, content: h.texto })),
      { role: 'user', content: mensajeUsuario }
    ];

    const completion = await groq.chat.completions.create({
      messages: mensajes,
      model: 'llama-3.3-70b-versatile'
    });

    const respuesta = completion.choices[0].message.content;

    historial.push({ role: 'user', texto: mensajeUsuario });
    historial.push({ role: 'assistant', texto: respuesta });
    guardarMemoria(historial);

    res.json({ respuesta });
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: 'Error al conectar con Jarvis' });
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Jarvis corriendo en http://localhost:${PORT}`));
