# petstore-v2-mcp · MCP Server（由 MCPForge 生成）

源 API：`https://petstore.swagger.io/v2`

工具数：20

该 API 无需鉴权。

## 运行

```bash
pip install -r requirements.txt
# stdio 调试
fastmcp dev server.py
# 暴露为 HTTP 服务
fastmcp run server.py --transport streamable-http --port 8080
```

## 工具清单

- `uploadFile` — [POST] /pet/{petId}/uploadImage（uploads an image）
- `addPet` — [POST] /pet（Add a new pet to the store）
- `updatePet` — [PUT] /pet（Update an existing pet）
- `findPetsByStatus` — [GET] /pet/findByStatus（Finds Pets by status）
- `findPetsByTags` — [GET] /pet/findByTags（Finds Pets by tags）
- `getPetById` — [GET] /pet/{petId}（Find pet by ID）
- `updatePetWithForm` — [POST] /pet/{petId}（Updates a pet in the store with form data）
- `deletePet` — [DELETE] /pet/{petId}（Deletes a pet）
- `getInventory` — [GET] /store/inventory（Returns pet inventories by status）
- `placeOrder` — [POST] /store/order（Place an order for a pet）
- `getOrderById` — [GET] /store/order/{orderId}（Find purchase order by ID）
- `deleteOrder` — [DELETE] /store/order/{orderId}（Delete purchase order by ID）
- `createUsersWithListInput` — [POST] /user/createWithList（Creates list of users with given input array）
- `getUserByName` — [GET] /user/{username}（Get user by user name）
- `updateUser` — [PUT] /user/{username}（Updated user）
- `deleteUser` — [DELETE] /user/{username}（Delete user）
- `loginUser` — [GET] /user/login（Logs user into the system）
- `logoutUser` — [GET] /user/logout（Logs out current logged in user session）
- `createUsersWithArrayInput` — [POST] /user/createWithArray（Creates list of users with given input array）
- `createUser` — [POST] /user（Create user）
