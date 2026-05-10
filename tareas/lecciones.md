# Lecciones

- Verificar el numero exacto del issue activo antes de consolidar agentes,
  checklist o bitacora local. Si el usuario corrige el numero, pivotar de
  inmediato y limpiar referencias del issue anterior.
- No publicar comandos de recuperacion que el parser aun no soporta. Si una
  ruta online no existe, el error debe decir el modo disponible y no inventar
  `login` pendiente.
- En importadores financieros, nunca ignorar pagos aprobados por errores de
  parser. La ingestion debe fallar antes de escribir staging/OFX o crear una
  evidencia revisable.
- No normalizar montos negativos con valor absoluto. Rechazar o modelar
  explicitamente reversas/devoluciones, con pruebas de semantica financiera.
- Si el usuario rechaza canales o proveedores concretos para una funcion,
  eliminarlos del producto y dejar el flujo local/minimo antes de seguir con
  integraciones externas.
