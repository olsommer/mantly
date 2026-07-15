/// <reference path="../pb_data/types.d.ts" />
migrate((app) => {
  const collection = app.findCollectionByNameOrId("pbc_209509107")

  // add field
  collection.fields.addAt(21, new Field({
    "hidden": false,
    "id": "bool3745876368",
    "name": "stripe_reported",
    "presentable": false,
    "required": false,
    "system": false,
    "type": "bool"
  }))

  return app.save(collection)
}, (app) => {
  const collection = app.findCollectionByNameOrId("pbc_209509107")

  // remove field
  collection.fields.removeById("bool3745876368")

  return app.save(collection)
})
