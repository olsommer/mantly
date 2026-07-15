/// <reference path="../pb_data/types.d.ts" />
migrate((app) => {
  const collection = app.findCollectionByNameOrId("_pb_users_auth_")

  // add field
  collection.fields.addAt(14, new Field({
    "hidden": false,
    "id": "bool932528226",
    "name": "password_login_enabled",
    "presentable": false,
    "required": false,
    "system": false,
    "type": "bool"
  }))

  // add field
  collection.fields.addAt(15, new Field({
    "autogeneratePattern": "",
    "hidden": false,
    "id": "text2278367884",
    "max": 0,
    "min": 0,
    "name": "login_code_hash",
    "pattern": "",
    "presentable": false,
    "primaryKey": false,
    "required": false,
    "system": false,
    "type": "text"
  }))

  // add field
  collection.fields.addAt(16, new Field({
    "hidden": false,
    "id": "date1776873248",
    "max": "",
    "min": "",
    "name": "login_code_expires",
    "presentable": false,
    "required": false,
    "system": false,
    "type": "date"
  }))

  // add field
  collection.fields.addAt(17, new Field({
    "hidden": false,
    "id": "number1616149536",
    "max": null,
    "min": null,
    "name": "login_code_attempts",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  return app.save(collection)
}, (app) => {
  const collection = app.findCollectionByNameOrId("_pb_users_auth_")

  // remove field
  collection.fields.removeById("bool932528226")

  // remove field
  collection.fields.removeById("text2278367884")

  // remove field
  collection.fields.removeById("date1776873248")

  // remove field
  collection.fields.removeById("number1616149536")

  return app.save(collection)
})
