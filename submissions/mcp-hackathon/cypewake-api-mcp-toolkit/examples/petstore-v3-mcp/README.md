# petstore-v3-mcp · MCP Server（由 MCPForge 生成）

源 API：`https://petstore3.swagger.io/api/v3`

工具数：19

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

- `updatePet` — [PUT] /pet（Update an existing pet.）
- `addPet` — [POST] /pet（Add a new pet to the store.）
- `findPetsByStatus` — [GET] /pet/findByStatus（Finds Pets by status.）
- `findPetsByTags` — [GET] /pet/findByTags（Finds Pets by tags.）
- `getPetById` — [GET] /pet/{petId}（Find pet by ID.）
- `updatePetWithForm` — [POST] /pet/{petId}（Updates a pet in the store with form data.）
- `deletePet` — [DELETE] /pet/{petId}（Deletes a pet.）
- `uploadFile` — [POST] /pet/{petId}/uploadImage（Uploads an image.）
- `getInventory` — [GET] /store/inventory（Returns pet inventories by status.）
- `placeOrder` — [POST] /store/order（Place an order for a pet.）
- `getOrderById` — [GET] /store/order/{orderId}（Find purchase order by ID.）
- `deleteOrder` — [DELETE] /store/order/{orderId}（Delete purchase order by identifier.）
- `createUser` — [POST] /user（Create user.）
- `createUsersWithListInput` — [POST] /user/createWithList（Creates list of users with given input array.）
- `loginUser` — [GET] /user/login（Logs user into the system.）
- `logoutUser` — [GET] /user/logout（Logs out current logged in user session.）
- `getUserByName` — [GET] /user/{username}（Get user by user name.）
- `updateUser` — [PUT] /user/{username}（Update user resource.）
- `deleteUser` — [DELETE] /user/{username}（Delete user resource.）
