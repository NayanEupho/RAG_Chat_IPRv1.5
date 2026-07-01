Features TBA:
1) batch durabilty: 
- Once a batch is drafted and saved/triggered for ingestion user can safely close the webiste and browser or logout and comeback later to see the progress and live view or see if the batch was successfully index

2) chunk view page:
- admin can search and select succsefully index docs from the list and view the chunks as they are stored in the db vs how model see's them during a model call with chunks
- for a selected doc user can view the chunks as cards with all the chunk metadata and copy the chunk and metadata and browse the chunks as cards in screen usng the <- and -> arrow keys or usng the "a" and "d" key as well 

3) vector stats page:
- Here admin can view all the vector stats like total documents index, total chunks, avg chunks per document, avg avg no. of tokens per chunks
- vector probe:
  - option to probe the vector database with a query to see what chunks are returned
  - we can select the option to see the each chunks retrived from vector db against our query and view them in the card view like system that I described earlier in chunk viewer 
  - we can also select the option to pass the retrived chunks through the re-ranker (also view the re-runker's name) and see the Final top-k chunks passed to the generator i.e to the model and option to increase/decrease the K value as well by deafult the k value is 5
  - a clear button to clear the results
