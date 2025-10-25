# Тестирование деплоя

1. Подготовил .env, по сути добавил только свой API_TOKEN с Groq платформы, а также токен тг бота.
2. Загрузил модели:
```bash
✅ Модели сохранены локально!
```
3. Подготовил данные в формате yaml в папке db_loader/data/ и запустил скрипт загрузки БД:
```bash
2025-10-25 17:02:41,701 [INFO] Loading SBERT model from local path: C:\Users\ggang\Desktop\rag_ai_helper\helper_services\ai_service\models\sbert_model
2025-10-25 17:02:41,704 [INFO] Use pytorch device_name: cpu
2025-10-25 17:02:41,704 [INFO] Load pretrained SentenceTransformer: C:\Users\ggang\Desktop\rag_ai_helper\helper_services\ai_service\models\sbert_model
2025-10-25 17:02:42,477 [INFO] 4 prompts are loaded, with the keys: ['classification', 'search_query', 'search_document', 'clustering']
2025-10-25 17:02:42,529 [INFO] Anonymized telemetry enabled. See                     https://docs.trychroma.com/telemetry for more information.
2025-10-25 17:02:42,955 [INFO] Найдено YAML файлов: 8
2025-10-25 17:02:42,955 [INFO] Загружаем файл: C:\Users\ggang\Desktop\rag_ai_helper\helper_services\db_loader\data\address.yaml
2025-10-25 17:02:42,957 [INFO] Загружаем файл: C:\Users\ggang\Desktop\rag_ai_helper\helper_services\db_loader\data\facultets.yaml
2025-10-25 17:02:42,974 [INFO] Загружаем файл: C:\Users\ggang\Desktop\rag_ai_helper\helper_services\db_loader\data\filial.yaml
2025-10-25 17:02:42,977 [INFO] Загружаем файл: C:\Users\ggang\Desktop\rag_ai_helper\helper_services\db_loader\data\history.yaml
2025-10-25 17:02:42,981 [INFO] Загружаем файл: C:\Users\ggang\Desktop\rag_ai_helper\helper_services\db_loader\data\kafedra_FIT.yaml
2025-10-25 17:02:42,988 [INFO] Загружаем файл: C:\Users\ggang\Desktop\rag_ai_helper\helper_services\db_loader\data\kafedra_MIEN.yaml
2025-10-25 17:02:42,997 [INFO] Загружаем файл: C:\Users\ggang\Desktop\rag_ai_helper\helper_services\db_loader\data\priem.yaml
2025-10-25 17:02:43,018 [INFO] Загружаем файл: C:\Users\ggang\Desktop\rag_ai_helper\helper_services\db_loader\data\transport.yaml
2025-10-25 17:02:43,023 [INFO] Итоговое кол-во чанков: 40
Batches: 100%|██████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████| 2/2 [01:22<00:00, 41.02s/it]
2025-10-25 17:04:05,332 [INFO] Загрузка базы данных завершена!
```
4. Переместил базу из db_loader/chroma_db в ai_service/chroma_db
5. Стартую контейнеры:
```bash
[+] Running 5/5
 ✔ ai_service     Built                                                                                                                                                                                    0.0s 
 ✔ tg_bot_service            Built                                                                                                                                                                                    0.0s 
 ✔ Network internal          Created                                                                                                                                                                                  0.1s 
 ✔ Container ai_service      Started                                                                                                                                                                                 10.2s 
 ✔ Container tg_bot_service  Started          
```
