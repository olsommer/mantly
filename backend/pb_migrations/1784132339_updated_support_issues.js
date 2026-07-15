/// <reference path="../pb_data/types.d.ts" />
migrate((app) => {
  const collection = app.findCollectionByNameOrId("pbc_1970072292")

  // add field
  collection.fields.addAt(30, new Field({
    "cascadeDelete": false,
    "collectionId": "pbc_1970072292",
    "hidden": false,
    "id": "relation3125327063",
    "maxSelect": 1,
    "minSelect": 0,
    "name": "merged_into_issue",
    "presentable": false,
    "required": false,
    "system": false,
    "type": "relation"
  }))

  return app.save(collection)
}, (app) => {
  const collection = app.findCollectionByNameOrId("pbc_1970072292")

  // remove field
  collection.fields.removeById("relation3125327063")

  return app.save(collection)
})
